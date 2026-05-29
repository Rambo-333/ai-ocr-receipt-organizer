# AI-OCR 請求書自動整理システム

OCRを使って紙の請求書・領収書を自動で読み取り、取引先ごとにフォルダ分けするデスクトップアプリです。

## 背景

経理部門では月300〜400枚の紙請求書をスキャン・仕分け・PDF変換する作業が発生しており、月16時間を費やしていました。  
本システムの導入により処理時間を約0.5時間に短縮し、**工数を97%削減**しました。

## 技術スタック

| 区分 | 技術 |
|------|------|
| 言語 | Python 3.x |
| UI | PySide6 (Qt6) |
| OCR | EasyOCR / Tesseract |
| 画像処理 | OpenCV / pdf2image / Poppler |
| データ管理 | Pandas / CSV |

## 主な機能

- PDF → 画像変換 → OCRテキスト抽出
- 取引先マスタ（CSV）との照合による自動仕分け
- 標準ファイル名の自動生成と宛先フォルダへの振り分け
- マルチスレッド処理によるバッチ実行（UIフリーズなし）
- リアルタイム進捗表示

## 処理フロー

```
1. 請求書PDF一括スキャン
   ↓
2. PDFを1ページずつ画像化（Poppler）
   ↓
3. 各ページをOCRで読み取り（EasyOCR / Tesseract）
   ↓
4. 取引先名・電話番号を抽出
   ↓
5. company_info.CSV と照合
   ↓
6. 取引先別にファイル名生成
   ↓
7. 出力フォルダに保存
```

## セットアップ

### 外部ツール（別途インストール）

- [Poppler](https://github.com/oschwartz10612/poppler-windows/releases/) — PDF変換に必要
- [Tesseract](https://github.com/UB-Mannheim/tesseract/wiki) — 補助OCRエンジン

ダウンロード後、プロジェクトルートに `poppler/` と `tesseract_bin/` として配置してください。

### インストール

```bash
python -m venv venv
venv\Scripts\activate

pip install -r requirements.txt
```

### 設定ファイル

```bash
copy config.sample.json config.json
copy company_info.sample.CSV company_info.CSV
```

`config.json` にPopplerとTesseractのパスを設定してください。

```json
{
  "own_company_info": {
    "name": "自社名",
    "tel": ["0000000000"],
    "fax": ["0000000001"]
  },
  "paths": {
    "poppler_path": "./poppler/bin",
    "tesseract_cmd": "./tesseract_bin/tesseract.exe"
  }
}
```

`company_info.CSV` に取引先情報を登録してください。

```csv
Company,tel,fax,terms
取引先A株式会社,0312345678,0312345679,
取引先B株式会社,0698765432,0698765433,1234567890123
```

### 起動

```bash
python ReceiptOrganizerApp_PySide6.py
```

## ファイル構成

```
.
├── ReceiptOrganizerApp_PySide6.py  # GUI・メインアプリ
├── ReceiptOrganizerExecutor.py     # OCR処理・ファイル操作ロジック
├── config.sample.json              # 設定ファイルサンプル
├── company_info.sample.CSV         # 取引先マスタサンプル
├── log_config.json                 # ログ設定
└── requirements.txt
```
