# Alpha Engine - Token Insider Intelligence

Auto-scan token baru dari DexScreener tiap 10 menit via GitHub Actions.
Score 1-100 + deployer quality + buy/sell ratio analysis.
Kirim alert ke Telegram kalau ada token potensial (score >= 60).

## Setup

1. Fork / clone repo ini
2. Set GitHub Secrets:
   - `TG_BOT_TOKEN` — token bot Telegram
   - `TG_CHAT_ID` — chat ID tujuan alert
3. Workflow jalan otomatis tiap 10 menit

## Cara Baca Score

| Score | Label | Arti |
|-------|-------|------|
| 80-100 | GOLD | Token bagus, socials lengkap, liq tinggi |
| 60-79 | SILVER | Potensial, masih bonding atau baru graduate |
| 40-59 | BRONZE | Masih early, perlu pantau |
| < 40 | WATCH | Kurang data atau red flag |

## Signal Analysis

- 🔥 ACCUM → Buy > 80% — orang banyak beli
- 📈 BUY>SELL → Buy 65-80% — dominan beli
- 🚨 DUMPING → Buy < 30% — orang jual besar