import os
import re
import json
import shutil
import easyocr
import pdf2image
import numpy as np
import pandas as pd
import cv2
import unicodedata
import PIL
import pytesseract
import threading
import concurrent.futures
import logging
from enum import Enum
from typing import Dict, List, Any

class MatchedType(Enum):
    NotFound = 0
    Undetermined = 1
    Confirmed = 2

class AbortException(Exception):
    def __init__(self, *args):
        super().__init__(*args)

class Executor():
    # 定型名詞をリストに設定
    __COMMON_COMPANY_SUFFIXES = ["株式会社", "有限会社", "（株）", "㈱", "（有）", "㈲"]
    # EasyOCRリーダーの初期化
    __reader = easyocr.Reader(['ja', 'en'])

    # number正規表現パターン：4桁以上の数字パターンを抽出
    __number_pattern = re.compile(r'\d{1,4}-?\d{1,4}-?\d{1,4}-?\d{1,4}')
    # company正規表現パターン
    __company_pattern = re.compile(r'(株式会社|（株）|㈱|有限会社|（有）|㈲)')

    def __init__(self, logger: logging.Logger, config_path: str = None):
        """
        Executorの初期化

        Args:
            logger: ロガーインスタンス
            config_path: config.jsonファイルのパス（デフォルトは同じディレクトリのconfig.json）

        Raises:
            FileNotFoundError: config.jsonが見つからない場合
            ValueError: config.jsonの内容が不正な場合
        """
        self.__logger = logger
        self.__abort_flag = False

        # config.jsonの読み込み
        if config_path is None:
            config_path = os.path.join(os.path.dirname(__file__), 'config.json')

        try:
            self.__config = self.__load_config(config_path)
            self.__logger.info(f"設定ファイルを読み込みました: {config_path}")
        except FileNotFoundError:
            self.__logger.error(f"設定ファイルが見つかりません: {config_path}")
            raise
        except json.JSONDecodeError as e:
            self.__logger.error(f"設定ファイルのJSON形式が不正です: {e}")
            raise ValueError(f"設定ファイルのJSON形式が不正です: {e}")
        except KeyError as e:
            self.__logger.error(f"設定ファイルに必須項目が不足しています: {e}")
            raise ValueError(f"設定ファイルに必須項目が不足しています: {e}")

        # 自社情報を設定から取得
        own_info = self.__config['own_company_info']
        self.__OWN_COMPANY_NAME = own_info['name']
        self.__OWN_COMPANY_TEL = own_info['tel']
        self.__OWN_COMPANY_FAX = own_info['fax']
        self.__IGNORE_COMPANY_NAME_VARIANTS = own_info['ignore_variants']

        # Tesseractのパスを設定
        tesseract_path = os.path.join(os.path.dirname(__file__), self.__config['paths']['tesseract_cmd'])
        pytesseract.pytesseract.tesseract_cmd = tesseract_path

        # CSVファイルから会社情報を読み込む
        csv_path = os.path.join(os.path.dirname(__file__), self.__config['paths']['company_info_csv'])
        try:
            self.__company_info_dict = self.__load_company_info_from_csv(csv_path)
            self.__logger.info(f"会社情報を読み込みました: {len(self.__company_info_dict)}件")
        except FileNotFoundError:
            self.__logger.error(f"会社情報CSVファイルが見つかりません: {csv_path}")
            raise
        except Exception as e:
            self.__logger.error(f"会社情報CSVファイルの読み込みに失敗しました: {e}")
            raise

        self.__counts = {MatchedType.Confirmed: {}, MatchedType.NotFound: {}, MatchedType.Undetermined: {}}
        self.__lock = threading.Lock()
        self.__process_thread = None
        self.__event_max_progress = None
        self.__event_add_progress = None
        self.__futures: list[concurrent.futures.Future] = []
        self.__event_abort_complete = None

    def __load_config(self, config_path: str) -> Dict[str, Any]:
        """
        config.jsonを読み込む

        Args:
            config_path: config.jsonのパス

        Returns:
            設定情報の辞書

        Raises:
            FileNotFoundError: ファイルが見つからない場合
            json.JSONDecodeError: JSON形式が不正な場合
            KeyError: 必須項目が不足している場合
        """
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"設定ファイルが見つかりません: {config_path}")

        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        # 必須項目のチェック
        required_keys = ['own_company_info', 'paths', 'processing_settings']
        for key in required_keys:
            if key not in config:
                raise KeyError(f"設定ファイルに'{key}'が定義されていません")

        # own_company_infoの必須項目チェック
        required_own_info = ['name', 'tel', 'fax', 'ignore_variants']
        for key in required_own_info:
            if key not in config['own_company_info']:
                raise KeyError(f"own_company_infoに'{key}'が定義されていません")

        # pathsの必須項目チェック
        required_paths = ['company_info_csv', 'tesseract_cmd', 'poppler_bin']
        for key in required_paths:
            if key not in config['paths']:
                raise KeyError(f"pathsに'{key}'が定義されていません")

        # processing_settingsの必須項目チェック
        required_settings = ['ocr_dpi', 'save_dpi', 'save_resolution', 'save_quality', 'max_workers']
        for key in required_settings:
            if key not in config['processing_settings']:
                raise KeyError(f"processing_settingsに'{key}'が定義されていません")

        return config

    # info_list
    def __load_company_info_from_csv(self, csv_path):
        """
        CSVファイルから会社情報を読み込み、辞書のリストとして返す。
        """
        df = pd.read_csv(csv_path, encoding='utf-8-sig').fillna('')
        df['Company'] = df['Company'].str.strip()
        df['tel'] = df['tel'].astype(str).str.strip().apply(self.__normalize_phone_number)
        df['fax'] = df['fax'].astype(str).str.strip().apply(self.__normalize_phone_number)
        df['terms'] = df['terms'].astype(str).str.strip().apply(self.__normalize_term)
        return df.to_dict('records')

    # 画像前処理
    def __preprocess_image(self, image):

        # テキスト向きによって画像を回転
        def correct_image_orientation(image):
            try:
                data = pytesseract.image_to_osd(image, output_type=pytesseract.Output.DICT)
            except pytesseract.TesseractError as e: # Tesseractで文字が読めない場合
                self.__logger.warning(f"TesseractError: {e}")
                return image # とりあえず画像はそのまま返す(EasyOCRで読むかもしれないので)
            angle = data['rotate'] # angleは0,90,180,270の4パターン
            if angle == 0:
                rotated_image = image
            elif angle == 90:
                rotated_image = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
            elif angle == 180:
                rotated_image = cv2.rotate(image, cv2.ROTATE_180)
            elif angle == 270:
                rotated_image = cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
            else: # ここには来ないはず
                rotated_image = image
            return rotated_image

        # 朱色(印鑑色)除去
        def mask_vermilion(image):
            hls_image = cv2.cvtColor(image, cv2.COLOR_RGB2HLS) # RGB->HLS
            # #D94236 <-> HLS(2,135,173)
            mask_lower1 = np.array([0, 1, 85])        # 抽出する色の下限
            mask_upper1 = np.array([20, 255, 255])    # 抽出する色の上限
            mask1 = cv2.inRange(hls_image, mask_lower1, mask_upper1) # マスクを作成
            mask_lower2 = np.array([175, 1, 85])      # 抽出する色の下限
            mask_upper2 = np.array([180, 255, 255])   # 抽出する色の上限
            mask2 = cv2.inRange(hls_image, mask_lower2, mask_upper2) # マスクを作成
            mask = cv2.bitwise_or(mask1, mask2)       # マスクを合成
            # HLSのL(輝度)を上げて白に近づける
            hls_image[:,:,1] = contrast_enhancement(hls_image[:,:,1], 0, 170, mask=mask)
            cvt_image = cv2.cvtColor(hls_image, cv2.COLOR_HLS2RGB) # HLS->RGB
            return cvt_image

        # コントラスト強調
        def contrast_enhancement(image, min, max, mask=None):
            x = np.arange(256)
            lut = np.zeros(256, dtype=np.uint8)
            # min未満は0固定(初期化時に0なので処理は行わない)
            # lut[x < min] = 0
            # min以上max未満は0-255へ補正
            mask_range = (min <= x) & (x < max)
            lut[mask_range] = np.round(255 * (x[mask_range] - min) / (max - min)).astype(np.uint8)

            # max以上は255固定
            lut[max <= x] = 255

            if mask is None:
                image_dst = cv2.LUT(image, lut)
            else: # maskが指定されたときはmask部分のみに適用
                image_dst = image.copy()
                image_dst[mask > 0] = cv2.LUT(image, lut)[mask > 0]
            return image_dst

        image = mask_vermilion(image) # 印鑑部分除去
        image = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) # グレースケール変換
        # 大津の二値化法で閾値を計算
        thresh, _ = cv2.threshold(image, 0, 255, cv2.THRESH_OTSU)
        lower = thresh / 2
        higher = (255 + thresh) / 2
        image = contrast_enhancement(image, lower, higher) # コントラスト強調(完全に二値化はしない)
        # アダプティブ閾値処理
        (h, w) = image.shape[:2]
        blockSize = min(h, w) // 12 * 2 + 1 # blockSizeは奇数である必要がある
        image = cv2.adaptiveThreshold(image, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, blockSize, 2)
        image = correct_image_orientation(image) # テキスト向きを修正
        return image

    # 読み込み画像確認(デバッグ用)
    def __save_tmp_image(self, image, name=None):
        return
        image_folder = os.path.join(os.path.dirname(__file__), "_tmp_image")
        if not os.path.exists(image_folder):
            os.makedirs(image_folder)
        if name is None:
            name = 'tmp_image'
        image_path = os.path.join(image_folder, f'{name}.png')
        image_pil = PIL.Image.fromarray(image)
        image_pil.save(image_path, "PNG")
        return

    # テキストクリーンアップ
    def __clean_text(self, text):
        # 全角から半角への変換
        text = text.translate(str.maketrans({
            'ａ': 'a', 'ｂ': 'b', 'ｃ': 'c', 'ｄ': 'd', 'ｅ': 'e', 'ｆ': 'f', 'ｇ': 'g', 'ｈ': 'h', 'ｉ': 'i', 'ｊ': 'j',
            'ｋ': 'k', 'ｌ': 'l', 'ｍ': 'm', 'ｎ': 'n', 'ｏ': 'o', 'ｐ': 'p', 'ｑ': 'q', 'ｒ': 'r', 'ｓ': 's',
            'ｔ': 't', 'ｕ': 'u', 'ｖ': 'v', 'ｗ': 'w', 'ｘ': 'x', 'ｙ': 'y', 'ｚ': 'z', 'Ａ': 'A', 'Ｂ': 'B',
            'Ｃ': 'C', 'Ｄ': 'D', 'Ｅ': 'E', 'Ｆ': 'F', 'Ｇ': 'G', 'Ｈ': 'H', 'Ｉ': 'I', 'Ｊ': 'J', 'Ｋ': 'K',
            'Ｌ': 'L', 'Ｍ': 'M', 'Ｎ': 'N', 'Ｏ': 'O', 'Ｐ': 'P', 'Ｑ': 'Q', 'Ｒ': 'R', 'Ｓ': 'S', 'Ｔ': 'T',
            'Ｕ': 'U', 'Ｖ': 'V', 'Ｗ': 'W', 'Ｘ': 'X', 'Ｙ': 'Y', 'Ｚ': 'Z', '１': '1', '２': '2', '３': '3',
            '４': '4', '５': '5', '６': '6', '７': '7', '８': '8', '９': '9', '０': '0', '　': ' '
        }))
        text = re.sub(r'[^\w\s]', '', text) # 記号や特殊文字を除去
        text = re.sub(r'\s+', '', text)  # 複数の空白を単一の空白に変換
        return text.strip()

    # 数字以外削除
    def __normalize_phone_number(self, number):
        return re.sub(r'\D', '', number)

    # info_listのterms前処理
    def __normalize_term(self, term):
        return re.sub(r'[-\s]', '', term)  # ハイフンと空白を削除

    # 前処理.数字
    # *********************************
    def __extract_phone_numbers(self, phone_numbers):
        phone_numbers = self.__number_pattern.findall(phone_numbers)
        return phone_numbers

    # 前処理.TERMS
    # *********************************
    def __extract_terms(self, text):
        terms = self.__number_pattern.findall(text)
        normalized_terms = []
        for term in terms:
            # ハイフンを除去して連続した数字に変換
            term = term.replace('-', '')
            if len(term) == 14:
                term = term[1:]  # 14桁の場合は先頭の文字を除去
            if len(term) >= 13:
                normalized_terms.append(term)
        return normalized_terms

    # 前処理.company
    # *********************************
    def __extract_company_names(self, text):
        words = text.split(', ')
        cleaned_companies = set()
        for word in words:
            if self.__company_pattern.search(word):
                cleaned_name = self.__clean_text(word)
                cleaned_companies.add(cleaned_name)
        return list(cleaned_companies)

    # 検索
    # *********************************
    def __find_best_match(self, text_parts):
        text = ', '.join(text_parts).strip()
        extracted_phone_numbers = self.__extract_phone_numbers(text)  # 前処理2.数字
        extracted_terms = self.__extract_terms(text)  # 前処理3.TERMS
        extracted_companies = self.__extract_company_names(text)

        # 番号前処理
        # ---------------------------------
        # 自社の電話番号とFAX番号を正規化してリストに格納
        own_company_tels = [self.__normalize_phone_number(tel) for tel in self.__OWN_COMPANY_TEL]
        own_company_faxes = [self.__normalize_phone_number(fax) for fax in self.__OWN_COMPANY_FAX]
        # 抽出された電話番号から自社の電話番号とFAX番号を除外
        filtered_numbers = [
            num for num in extracted_phone_numbers
            if num not in own_company_tels and num not in own_company_faxes
        ]

        # 検索
        # ---------------------------------
        matched_info = None
        matched_key = None
        matched_state = MatchedType.NotFound

        for info in self.__company_info_dict:
            # TELで検索（完全一致）
            if self.__normalize_phone_number(info['tel']) in filtered_numbers:
                matched_info = info
                matched_key = 'TEL'
                matched_state = MatchedType.Confirmed
                break

            # FAXで検索（完全一致）
            if self.__normalize_phone_number(info['fax']) in filtered_numbers:
                matched_info = info
                matched_key = 'FAX'
                matched_state = MatchedType.Confirmed
                break

            # TERMSで検索（完全一致）
            if extracted_terms:
                if info['terms'] in extracted_terms:
                    matched_info = info
                    matched_key = 'TERMS'
                    matched_state = MatchedType.Confirmed
                    break

                # TERMSで検索（先頭を除いた完全一致）
                stripped_company_terms = info['terms'][1:] if len(info['terms']) == 14 else info['terms']
                if stripped_company_terms in extracted_terms:
                    matched_info = info
                    matched_key = 'TERMS (先頭を除いた完全一致)'
                    matched_state = MatchedType.Confirmed
                    break

            # Companyで検索（自社名を除いた完全一致）
            # 株式会社や有限会社、（株）や(有)を含む完全一致
            cleaned_info_company = self.__clean_text(info['Company'])
            for company in extracted_companies:
                if company in self.__IGNORE_COMPANY_NAME_VARIANTS or self.__clean_text(company) == self.__clean_text(self.__OWN_COMPANY_NAME):
                    continue
                if cleaned_info_company == self.__clean_text(company):
                    matched_info = info
                    matched_key = 'Company (完全一致)'
                    matched_state = MatchedType.Confirmed
                    break
            if matched_state == MatchedType.Confirmed:
                break

            # Companyで検索（自社名を除いた部分一致）
            # 抽出された名前がプレフィックスなしでリストの会社名と完全一致するかを確認
            cleaned_info_company_no_prefix = self.__clean_text(re.sub(r'(株式会社|（株）|㈱|有限会社|（有）|㈲)', '', cleaned_info_company))
            if cleaned_info_company_no_prefix not in self.__IGNORE_COMPANY_NAME_VARIANTS and cleaned_info_company_no_prefix in text_parts:
                matched_info = info
                matched_key = 'Company (check)'
                matched_state = MatchedType.Undetermined
                continue

        # 検索結果
        # ---------------------------------
        if matched_info:
            tel = matched_info['tel'] if matched_info['tel'] else 'N/A'
            fax = matched_info['fax'] if matched_info['fax'] else 'N/A'
            company = matched_info['Company'] if matched_info['Company'] else 'N/A'
            terms = matched_info['terms'] if matched_info['terms'] else 'N/A'
            self.__logger.info(f"Matched {matched_key}: TEL: {tel}, FAX: {fax}, TERMS: {terms}, Company: {company}")
            return matched_info['Company'], matched_state
        else:
            self.__logger.info("__Uncategorized__")
            return "Uncategorized", matched_state

    # ファイル名 前処理
    # *********************************
    def __format_file_name(self, company_name, matched_state, outfile_suffix, count):
        file_name = re.sub(r'[\/:*?"<>|]', '', company_name)
        file_name = re.sub(r'\s+', '', file_name)
        file_name = file_name.strip()
        file_name = unicodedata.normalize('NFKC', file_name)
        file_name = file_name[:50]
        check = "(check)" if matched_state == MatchedType.Undetermined else ""
        file_name = f'{file_name}_{outfile_suffix}-{count:03d}{check}.pdf'
        return file_name

    def __extract_company_info(self, image):
        result = self.__reader.readtext(image)  # 画像からテキスト抽出
        text_parts = []
        for (_, text_part, confidence) in result:
            cleaned_text_part = self.__clean_text(text_part)  # テキストクリーンアップ
            text_parts.append(cleaned_text_part)
            self.__logger.debug(f"Recognized text: {cleaned_text_part}(confidence:{confidence:.2f})")  # デバッグ用にクリーンアップ後のOCR結果を表示
        return self.__find_best_match(text_parts)

    def __process_pdf(self, pdf_path, output_folder, outfile_suffix):
        """
        PDFファイルを処理してOCRで会社を判定し、仕分けて保存する

        Args:
            pdf_path: 処理するPDFファイルのパス
            output_folder: 出力先フォルダ
            outfile_suffix: 出力ファイル名のサフィックス（年月）
        """
        try:
            self.__raise_if_aborting()
            if not os.path.exists(pdf_path):
                self.__logger.warning(f"ファイルが見つかりません: {pdf_path}")
                return

            self.__logger.info(f"PDFファイル処理開始: {os.path.basename(pdf_path)}")

            # 設定から値を取得
            poppler_dir = os.path.join(os.path.dirname(__file__), self.__config['paths']['poppler_bin'])
            ocr_dpi = self.__config['processing_settings']['ocr_dpi']
            save_dpi = self.__config['processing_settings']['save_dpi']
            save_resolution = self.__config['processing_settings']['save_resolution']
            save_quality = self.__config['processing_settings']['save_quality']

            # OCR用に高DPIで読み込み
            try:
                images_ocr = pdf2image.convert_from_path(pdf_path, dpi=ocr_dpi, poppler_path=poppler_dir)
            except Exception as e:
                self.__logger.error(f"PDFの画像変換に失敗しました ({os.path.basename(pdf_path)}): {e}")
                return

            self.__raise_if_aborting()

            # 各ページをOCR処理
            results = []
            for page_num, image in enumerate(images_ocr, start=1):
                self.__raise_if_aborting()
                try:
                    image_np = np.array(image)
                    processed_image = self.__preprocess_image(image_np)
                    self.__save_tmp_image(processed_image)
                    self.__raise_if_aborting()
                    matched_company, matched_state = self.__extract_company_info(processed_image)
                    results.append((matched_company, matched_state))
                    self.__logger.debug(f"ページ{page_num}の処理完了: {matched_company}")
                except Exception as e:
                    self.__logger.error(f"ページ{page_num}のOCR処理に失敗しました: {e}")
                    # エラーが発生したページはUncategorizedとして扱う
                    results.append(("Uncategorized", MatchedType.NotFound))

            self.__raise_if_aborting()

            # 1ページのPDFの場合は元のファイルをコピー、複数ページの場合は画像として保存
            if len(results) == 1:
                # 1ページのPDF: 元のファイルをそのままコピー（ファイルサイズを維持）
                matched_company_, matched_state_ = results[0]

                with self.__lock:
                    count = 1 + self.__counts[matched_state_].setdefault(matched_company_, 0)
                    self.__counts[matched_state_][matched_company_] = count

                file_name = self.__format_file_name(matched_company_, matched_state_, outfile_suffix, count)
                if matched_state_ == MatchedType.Undetermined:
                    folder_name = "Check"
                elif matched_state_ == MatchedType.NotFound:
                    folder_name = "Uncategorized"
                else:
                    folder_name = "Categorized"

                folder_path = os.path.join(output_folder, folder_name)
                try:
                    if not os.path.exists(folder_path):
                        os.makedirs(folder_path)
                except Exception as e:
                    self.__logger.error(f"出力フォルダの作成に失敗しました ({folder_path}): {e}")
                    return

                new_pdf_path = os.path.join(folder_path, file_name)

                # 元のPDFファイルを直接コピー
                try:
                    shutil.copy2(pdf_path, new_pdf_path)
                    self.__logger.info(f"保存完了（元ファイルコピー）: {file_name}")
                except Exception as e:
                    self.__logger.error(f"PDFのコピーに失敗しました ({file_name}): {e}")
                    return

                # 進捗を加算
                with self.__lock:
                    if self.__event_add_progress is not None:
                        self.__event_add_progress(1)
            else:
                # 複数ページのPDF: 保存用に低DPIで画像変換してファイルサイズを削減
                try:
                    images_save = pdf2image.convert_from_path(pdf_path, dpi=save_dpi, poppler_path=poppler_dir)
                except Exception as e:
                    self.__logger.error(f"保存用の画像変換に失敗しました ({os.path.basename(pdf_path)}): {e}")
                    return

                self.__raise_if_aborting()

                # 各ページを個別のPDFとして保存
                for page_num, (image_, (matched_company_, matched_state_)) in enumerate(zip(images_save, results), start=1):
                    with self.__lock:
                        count = 1 + self.__counts[matched_state_].setdefault(matched_company_, 0)
                        self.__counts[matched_state_][matched_company_] = count

                    file_name = self.__format_file_name(matched_company_, matched_state_, outfile_suffix, count)
                    if matched_state_ == MatchedType.Undetermined:
                        folder_name = "Check"
                    elif matched_state_ == MatchedType.NotFound:
                        folder_name = "Uncategorized"
                    else:
                        folder_name = "Categorized"

                    folder_path = os.path.join(output_folder, folder_name)
                    try:
                        if not os.path.exists(folder_path):
                            os.makedirs(folder_path)
                    except Exception as e:
                        self.__logger.error(f"出力フォルダの作成に失敗しました ({folder_path}): {e}")
                        continue

                    new_pdf_path = os.path.join(folder_path, file_name)

                    # 画像をPDFとして保存（圧縮設定を最適化）
                    try:
                        image_rgb = image_.convert('RGB')
                        image_rgb.save(new_pdf_path, "PDF", resolution=save_resolution, quality=save_quality, optimize=True)
                        self.__logger.info(f"保存完了（圧縮）: {file_name}")
                    except Exception as e:
                        self.__logger.error(f"PDFの保存に失敗しました ({file_name}): {e}")
                        continue

                    # 各ページごとに進捗を加算
                    with self.__lock:
                        if self.__event_add_progress is not None:
                            self.__event_add_progress(1)

            # 元のPDFファイルを削除
            try:
                os.remove(pdf_path)
                self.__logger.info(f"元のファイルを削除しました: {os.path.basename(pdf_path)}")
            except Exception as e:
                self.__logger.warning(f"元のファイルの削除に失敗しました ({os.path.basename(pdf_path)}): {e}")
        except Exception as e:
            self.__logger.error(f"PDFファイル処理中にエラーが発生しました。{os.path.basename(pdf_path)}: {e}")
            # 中止時はabort_complete_signalをemit（多重emit防止）
            if self.__abort_flag and self.__event_abort_complete:
                self.__logger.debug("中止完了シグナルを送信 (from __process_pdf)")
                self.__event_abort_complete()
                self.__event_abort_complete = None

    def __organize_pdfs_by_company(self, pdf_folder, outfile_suffix, max_workers):
        self.__abort_flag = False
        self.__event_abort_complete_emitted = False  # emit済みフラグ追加
        pdf_files = [os.path.join(pdf_folder, f) for f in os.listdir(pdf_folder) if f.endswith('.pdf')]
        # すべてのPDFのページ数合計を計算
        total_pages = 0
        for pdf_file in pdf_files:
            try:
                poppler_dir = os.path.join(os.path.dirname(__file__), 'poppler', 'bin')
                images = pdf2image.convert_from_path(pdf_file, dpi=50, poppler_path=poppler_dir)
                total_pages += len(images)
            except Exception as e:
                self.__logger.warning(f"ページ数取得失敗: {pdf_file}: {e}")
                total_pages += 1  # 失敗時も1ページとしてカウント
        if self.__event_max_progress is not None:
            self.__event_max_progress(total_pages)
        if self.__event_add_progress is not None:
            self.__event_add_progress(0)
        with concurrent.futures.ThreadPoolExecutor(max_workers = max_workers) as executor:
            self.__futures = [executor.submit(self.__process_pdf, pdf_file, pdf_folder, outfile_suffix) for pdf_file in pdf_files]
            for future in concurrent.futures.as_completed(self.__futures):
                try:
                    future.result()
                except concurrent.futures.CancelledError:
                    pass
                except Exception as e:
                    self.__logger.error(f"Error in processing: {e}")

        # ログを書き込む
        if not self.__abort_flag:
            counts_total = {k: sum(v.values()) for k, v in self.__counts.items()}
            total = sum(counts_total.values())
            categorized_ratio = counts_total[MatchedType.Confirmed] / total * 100 if total > 0 else 0
            uncategorized_ratio = counts_total[MatchedType.NotFound] / total * 100 if total > 0 else 0
            check_ratio = counts_total[MatchedType.Undetermined] / total * 100 if total > 0 else 0
            log_data = [
                f"{counts_total[MatchedType.Confirmed]} ({categorized_ratio:.2f}%)",
                f"{counts_total[MatchedType.NotFound]} ({uncategorized_ratio:.2f}%)",
                f"{counts_total[MatchedType.Undetermined]} ({check_ratio:.2f}%)",
                f"{total}"
            ]
            self.__logger.info(", ".join(log_data))
        # 中止完了時コールバック
        if self.__abort_flag and hasattr(self, "__event_abort_complete") and self.__event_abort_complete:
            self.__logger.debug("中止完了シグナルを送信 (from __organize_pdfs_by_company)")
            self.__event_abort_complete()
            self.__event_abort_complete = None

    def __raise_if_aborting(self):
        if self.__abort_flag:
            raise AbortException("処理は中断されました。")

    def abort(self):
        if self.is_running():
            for future in self.__futures:
                future.cancel()
            self.__abort_flag = True

    def is_running(self):
        return self.__process_thread and self.__process_thread.is_alive()

    def is_aborted(self):
        return self.__abort_flag

    def is_completed(self):
        return not self.is_running() and not self.is_aborted()

    def set_event_max_progress(self, action):
        self.__event_max_progress = action

    def set_event_add_progress(self, action):
        self.__event_add_progress = action

    def set_event_abort_complete(self, action):
        self.__event_abort_complete = action

    def start(self, pdf_folder, outfile_suffix, max_workers: int | None = None):
        if self.is_running():
            raise AssertionError()
        self.__process_thread = threading.Thread(target=self.__organize_pdfs_by_company, args=(pdf_folder, outfile_suffix, max_workers))
        self.__process_thread.start()
        # スレッドがis_alive()になるまで少し待つ
        import time
        for _ in range(10):
            if self.__process_thread.is_alive():
                break
            time.sleep(0.01)
