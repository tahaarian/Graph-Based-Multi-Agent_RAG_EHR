# EHR Graph-RAG: Dynamic Graph-Based Multi-Agent RAG Framework for Longitudinal EHRs

## چکیده (Abstract)

این پروژه یک چارچوب **Graph-RAG چندعاملی و مبتنی بر گراف پویا** برای بازیابی وفادارانه (Faithful Retrieval) و تصمیم‌گیری استدلالی (Reasoned Decision-Making) روی **الکترونیک سوابق سلامت طولی (Longitudinal EHRs)** است. به‌جای بازیابی برداریِ صرف، تاریخچه بیمار به‌صورت یک **گراف ناهمگن پویا** (شامل بیمار، ویزیت، بیماری، دارو، آزمایش و پروسیجر) مدل‌سازی می‌شود و با ترکیب **مسیر‌یابی معنایی-زمانی** و **اجماع چندعاملی**، پاسخ‌هایی قابل‌ردیابی و مبتنی بر شواهد تولید می‌گردد. هدف نهایی، انتشار یک مقاله در مجلات **Q1** است که روی بنچمارک عمومی **EHRSHOT** و طرح مشترک **OMOP CDM v5.4** ارزیابی می‌شود.

## راه‌اندازی (Setup)

### روش اصلی: Conda (توصیه‌شده)

```bash
conda env create -f environment.yml
conda activate ehr-graph-rag
```

### روش جایگزین: pip

```bash
python -m venv .venv
source .venv/bin/activate   # ویندوز: .venv\Scripts\activate
pip install -r requirements.txt
# توجه: torch-geometric برای نصب به ایندکس چرخ‌های (wheel) اختصاصی PyG نیاز دارد؛
# در صورت خطا به https://pytorch-geometric.readthedocs.io/en/latest/installation.html مراجعه کنید:
pip install torch_geometric -f https://data.pyg.org/whl/torch-${TORCH_VERSION}+${CUDA}.html
```

## پیکربندی (Configuration)

```bash
cp .env.example .env
# سپس مقادیر واقعی NEO4J_PASSWORD ،QDRANT_API_KEY و ... را در .env وارد کنید.
# هرگز فایل .env را به git کامیت نکنید (در .gitignore پوشش داده شده است).
```

## اعتبارسنجی محیط

```bash
python scripts/check_environment.py   # بررسی نسخه پایتون و پکیج‌های نصب‌شده
python scripts/test_db_connections.py # تست اتصال به Neo4j و Qdrant
```

## ساختار پروژه

```
ehr-graph-rag/
├── config/            # تنظیمات pydantic-settings و لاگ‌گیری
├── data/
│   ├── raw/           # CSVهای خام OMOP CDM v5.4 (کامیت نمی‌شود)
│   ├── processed/     # داده پاک‌سازی‌شده و نگاشت‌شده به اسکیمای داخلی
│   └── external/      # داده کمکی (فرهنگ‌های داده، واژگان)
├── docs/              # معماری و مستندات
├── scripts/           # check_environment.py ، test_db_connections.py
├── src/ehr_graph_rag/
│   ├── ingestion/     # فاز ۱: بارگذاری EHRSHOT / OMOP CDM v5.4
│   ├── graph/         # فاز ۲: گراف ناهمگن پویا (Neo4j + PyG + SapBERT)
│   ├── retrieval/     # فاز ۳: بازیابی مسیر معنایی-زمانی TSPR
│   ├── agents/        # فاز ۴: اجماع چندعاملی CMAC (LangGraph)
│   ├── evaluation/    # فاز ۵: AUROC / F1 / RAGAS faithfulness
│   └── utils/         # کلاینت‌های دیتابیس و ابزارهای مشترک
└── tests/             # تست‌های pytest
```

## نقشه راه (Roadmap)

| فاز | عنوان | شرح |
|-----|-------|-----|
| ۰ | Infrastructure | راه‌اندازی ریپو، محیط conda، کلاینت‌های Neo4j/Qdrant |
| ۱ | Ingestion | بارگذاری و اعتبارسنجی داده EHRSHOT بر پایه OMOP CDM v5.4 |
| ۲ | Dynamic Heterogeneous Graph | ساخت گراف پویا در Neo4j و امبدینگ گره‌ها با PyG و SapBERT |
| ۳ | TSPR | بازیابی مسیر معنایی-زمانی (Temporal-Semantic Path Retrieval) |
| ۴ | CMAC | اجماع چندعاملی (تشخیص/داروشناسی/آزمایش) با LangGraph |
| ۵ | Evaluation | سنجش AUROC ،F1 و وفاداری RAGAS |
