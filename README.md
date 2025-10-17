# AI-OCR請求書自動処理システム

![Python](https://img.shields.io/badge/python-3.8+-blue.svg)
![PySide6](https://img.shields.io/badge/PySide6-GUI-green.svg)
![EasyOCR](https://img.shields.io/badge/EasyOCR-AI-orange.svg)

総務部が抱える月間300-400枚の紙請求書の仕分け・PDF化作業を、AI-OCRで自動化するシステムです。

## 📋 概要

**解決した課題:**
- 月間300-400枚の紙請求書を手作業で業者別に仕分け
- 業者ごとにPDFファイル化する作業に**月2日(16時間)**を要していた
- 電子帳簿保存法対応のため、電子化が急務

**実装した解決策:**
- EasyOCR(AI-OCR)で請求書から自動的に情報抽出
- 取引先名・金額・日付を自動認識
- 業者別にファイル分割し、適切なファイル名で保存
- GUIアプリケーションで直感的な操作を実現

## 💰 ビジネスインパクト

- **工数削減:** 月16時間 → 約1時間 (約94%削減)
- **精度向上:** 手作業による仕分けミスを大幅削減
- **法対応:** 電子帳簿保存法への準拠を実現
- **生産性:** 総務部の工数を高付加価値業務にシフト

## 🛠️ 技術スタック

### AI/OCR
- **EasyOCR** - 日本語OCRエンジン
- **Tesseract** - 補助OCRエンジン
- **OpenCV** - 画像前処理

### GUI/処理
- **PySide6 (Qt6)** - GUIフレームワーク
- **pdf2image** - PDF→画像変換
- **Poppler** - PDFレンダリング
- **Pandas** - データ処理

### 特徴
- マルチスレッド処理で大量ファイルを高速処理
- 進捗バー・ログ表示で処理状況を可視化
- CSVベースの取引先データベース管理

## 📁 プロジェクト構成

```
ReceiptOrganizer/
├── ReceiptOrganizerApp_PySide6.py    # GUIメインアプリケーション
├── ReceiptOrganizerExecutor.py      # OCR処理・PDF分割ロジック
├── config.sample.json                # 設定ファイルテンプレート
├── company_info.sample.CSV           # 取引先情報サンプル
├── log_config.json                   # ログ設定
├── requirements.txt                  # Python依存関係
├── .env.example                      # 環境変数テンプレート
└── README.md
```

**注意:** `poppler/`と`tesseract_bin/`は外部ツールです。本リポジトリに含まれていますが、ライセンスは各プロジェクトに従います。セットアップ手順も参照してください。

## 🚀 セットアップ方法

### 前提条件

- Python 3.8以上
- Windows OS (Poppler/Tesseractのパスが前提)

### インストール手順

#### 1. **リポジトリのクローン:**
```bash
git clone https://github.com/Rambo-333/ai-ocr-receipt-organizer.git
cd ai-ocr-receipt-organizer
```

#### 2. **仮想環境の作成:**
```bash
python -m venv venv
venv\Scripts\activate  # Windows
```

#### 3. **依存関係のインストール:**
```bash
pip install -r requirements.txt
```

#### 4. **外部ツールのセットアップ:**

**Poppler (PDF→画像変換):**
- [Poppler for Windows](https://github.com/oschwartz10612/poppler-windows/releases/)をダウンロード
- `poppler/`フォルダに展開
- `poppler/bin/`にPATHを通す

**Tesseract (OCRエンジン):**
- [Tesseract-OCR](https://github.com/UB-Mannheim/tesseract/wiki)をダウンロード
- `tesseract_bin/`フォルダに展開
- 日本語データ(jpn.traineddata)をtessdata/に配置

#### 5. **設定ファイルの作成:**
```bash
copy config.sample.json config.json
copy company_info.sample.CSV company_info.CSV
```

#### 6. **config.jsonの編集:**
```json
{
  "own_company_info": {
    "name": "あなたの会社名",
    "tel": ["0000000000"],
    "fax": ["0000000001"]
  },
  "paths": {
    "poppler_path": "./poppler/bin",
    "tesseract_cmd": "./tesseract_bin/tesseract.exe"
  }
}
```

#### 7. **取引先情報の登録:**
`company_info.CSV`に取引先情報を登録:
```csv
Company,tel,fax,terms
取引先A株式会社,0312345678,0312345679,
取引先B株式会社,0698765432,0698765433,1234567890123
```

#### 8. **アプリケーションの起動:**
```bash
python ReceiptOrganizerApp_PySide6.py
```

## 📊 主要機能

### 1. AI-OCR自動認識
- EasyOCRで請求書全体をスキャン
- 取引先名を自動抽出(正規表現+AI)
- 金額・日付・注文番号も認識(拡張可能)

### 2. 自動ファイル分割
- 一括スキャンしたPDFを自動的にページ分割
- 取引先ごとにファイル名を生成
  - 例: `2025-01-15_サンプル商事株式会社_123456.pdf`
- 出力フォルダに整理して保存

### 3. GUIアプリケーション
- ファイル選択・出力先指定
- リアルタイム進捗表示
- ログウィンドウで処理状況を確認
- エラー時の詳細メッセージ表示

### 4. 取引先データベース管理
- CSV形式で取引先情報を管理
- 電話番号・FAX番号での照合
- 会社名のバリエーション対応

## 🔧 処理フロー

```
1. 請求書PDF一括スキャン
   ↓
2. PDFを1ページずつ画像化(Poppler)
   ↓
3. 各ページをOCRで読み取り(EasyOCR/Tesseract)
   ↓
4. 取引先名・電話番号を抽出
   ↓
5. company_info.CSVと照合
   ↓
6. 取引先別にファイル名生成
   ↓
7. 出力フォルダに保存
```

## 🎯 技術的なポイント

### AI-OCRの実装
```python
# EasyOCRの初期化(日本語モデル)
reader = easyocr.Reader(['ja'], gpu=False)

# 画像からテキスト抽出
results = reader.readtext(image)

# 取引先名の抽出(正規表現+AI)
company_pattern = re.compile(r'(株式会社|（株）|㈱|有限会社)')
for text in results:
    if company_pattern.search(text):
        # 会社名の候補として処理
```

### マルチスレッド処理
- PySide6のQThreadで別スレッド実行
- UIをブロックせずバックグラウンドで処理
- 進捗シグナルでリアルタイム更新

### エラーハンドリング
- OCR失敗時の代替処理
- PDF読み込みエラーのログ記録
- 未登録の取引先への対応

### パフォーマンスと運用

**処理時間:**
- 月間300-400枚の請求書処理に約1時間(GPU非搭載PC)
- 実運用では夜間バッチ処理として実行(帰宅時に実行 → 翌朝完了)
- GPU搭載PCを使用すれば、さらなる高速化が可能

**運用の工夫:**
- 担当者は処理中に他の業務を並行して実施
- 専用PCを用意することで、メインPCの作業を妨げない運用も可能

## 📝 開発の経緯

このプロジェクトは、総務部からの「請求書処理に時間がかかりすぎる」という相談から始まりました。

1. **課題のヒアリング**: 月2日(16時間)の手作業
2. **技術調査**: OCRライブラリの比較検証
3. **プロトタイプ開発**: コマンドライン版で検証
4. **GUI化**: 総務担当者でも使いやすいインターフェース
5. **実運用**: 月1回の定期処理で94%の工数削減を実現

## 🚫 制限事項

- **OCR精度**: 手書き文字や低解像度には対応困難
- **フォーマット**: 請求書のレイアウトが大きく異なる場合は要調整
- **OS依存**: Windows前提(Poppler/Tesseractのパス)

## 👤 作成者

**Rambo**
- GitHub: [@Rambo-333](https://github.com/Rambo-333)

## 📝 このプロジェクトについて

本プロジェクトは総務部の業務効率化要請に応えて開発されました。以下のスキルを証明します:

- AI技術(OCR)の実務適用能力
- 業務フローの理解と自動化設計
- GUIアプリケーション開発
- 実測可能な成果(工数94%削減)

---

**ポートフォリオ注記**: これは実際の業務で使用されているシステムをサニタイズしたバージョンです。企業固有の情報、取引先データは全て削除されています。
