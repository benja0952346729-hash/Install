# 🎰 Lottery Bot AI Training System

## አጠቃላይ እይታ

ይህ system 2 ክፍል አለው:
1. **Node.js Bot** — Telegram group ውስጥ ሁሉንም events ያስቀምጣል
2. **Python Trainer** — ያንን data ወስዶ AI ያስተምራል

---

## 🌐 Language Detection

Bot ሰው የጻፈበትን ቋንቋ ተረድቶ ያንኑ ቋንቋ ይመልሳል:

```
ሰው: "5 ያዝ"      → Bot: "እሺ 🙏 ገቢ"
ሰው: "5 take"     → Bot: "Done 🙏 registered"
ሰው: "21 half"    → Bot: "Done 🙏 registered"
ሰው: "21 ግማሽ"    → Bot: "እሺ 🙏 ገቢ"
ሰው: "21 gmash"   → Bot: "እሺ 🙏 ገቢ"  (አማርኛ dominant)
```

- አማርኛ ጻፈ → አማርኛ መልስ
- English ጻፈ → English መልስ
- Mixed → dominant language

---

## 📋 የጨዋታ Rules

### Board
- **100 slots** (01–100)
- **20 ሰው** — እያንዳንዱ **5 consecutive slots** ይወስዳል
- ሙሉ = **400 ብር** | ግማሽ = **200 ብር**
- 🥇 1ኛ = 5,000ብር | 🥈 2ኛ = 1,000ብር | 🥉 3ኛ = 400ብር

### Payment Banks
- CBE, Awash, Dashen, Tele Birr

---

## 👤 Slot Registration Rules

### ስም Format
| ሁኔታ | Format |
|------|--------|
| ሙሉ | `አበበ` |
| ግማሽ (1 ሰው) | `አበበ +` |
| ግማሽ (2 ሰው) | `አበበ + አየለ` |
| ተመሳሳይ ስም | `አበበ 2`, `አበበ 3` |
| 1 ሰው ብዙ slot | ስሙ ይደጋገማል |

### Payment Status
| Format | ትርጉም |
|--------|--------|
| `አበበ` | ገና አልከፈለም |
| `አበበ ✅` | ሙሉ ከፍሏል |
| `አበበ ✅+` | አበበ ከፍሏል፣ አጋር ይፈልጋል |
| `አበበ + አየለ` | ሁለቱም ያልከፈሉ |
| `አበበ ✅+ አየለ` | አበበ ከፍሏል፣ አየለ ያልከፈለ |
| `አበበ + አየለ ✅` | አየለ ከፍሏል፣ አበበ ያልከፈለ |
| `አበበ ✅+ አየለ ✅` | ሁለቱም ከፈሉ |

### አጋር ሲወጣ
```
አበበ + አየለ → አበበ ወጣ → አየለ +
አበበ ✅+ አየለ → አበበ ወጣ → አየለ +
አበበ + አየለ ✅ → አበበ ወጣ → አየለ ✅+
```

### Upgrade / Downgrade
- ለውጥ ሲደረግ payment **reset** ይሆናል (✅ ያልነበረ)
- ✅ ካለ ከቀየረ → ቀሪ ሂሳብ ይሰላል
- `አበበ ✅+` → ሙሉ → 200ብር ይጨምራል → `አበበ ✅`
- `አበበ ✅` → ግማሽ → 200ብር ይመለሳል → `አበበ ✅+`

---

## 💬 የሰው Request Styles

### ቁጥር የሚጠይቁባቸው መንገዶች
```
01 ያዝ / 5 ያዝ / 01-05
3 / 01 / 5           ← ቁጥር ብቻ
3,1                  ← comma = separator
21 35                ← space = separator
31/21/41/            ← / = separator
```

### ግማሽ Keywords (ሁሉም አንድ ትርጉም)
```
አማርኛ:  +  ÷  ግ  ግማሽ  በግማሽ
English: +  g  gm  gmash  half
```

### ሙሉ Keywords
```
አማርኛ:  ሙሉ  በሙሉ
English: mulu  bemulu  full
(ምንም keyword = default ሙሉ)
```

### Global Keywords
```
"ሁሉንም በሙሉ"  → ሁሉም ሙሉ
"ሁሉንም +"     → ሁሉም ግማሽ
"ሁሉንም በግማሽ" → ሁሉም ግማሽ
```

### ለሌላ ሰው መመዝገብ
```
11 አበበ በል / 11 አበበ ብለህ ያዝ / 11 abebe register
21 41 51 አበበ             → ሦስቱም = አበበ
31 አቤል 21+ አበበ          → 31=አቤል, 21+=አበበ
```

### ግራ የሚያጋቡ requests
```
41 51 61+  → መጨረሻ ላይ + ብቻ = bot ይጠይቃል
Bot: "61 ብቻ በግማሽ ነው ልያዝልህ?"
አዎ → 61+ ብቻ
አይ → ሁሉም + ምሳሌ ይሰጣል
```

---

## 🤖 Bot Responses

### ቁጥር ሲመዘገብ
```
እሺ 🙏 ገቢ
ቤተሰብ ገቢ 🙏
ገቢ እንዳይረሳ 🙏
እሺ ይፍጠን 🙏  ← ወደ መጨረሻ ሲቃረብ
ተቀደምክ 🙏   ← ቀድሞ ተወስዷል
ተይዟል ይቅርታ 🙏
```

### ቀሪ ቁጥር
- 7 በታች → ይዘረዝራል (ሙሉ መጀመሪያ፣ ግማሽ ሲጠየቅ)
- 7 በላይ → "አለ 🙏 ብዙ ቁጥሮች አሉ"

### Slot ተይዞ + ሲኖር
```
ሰው: "01"  (01+ አለ)
Bot: "እሺ በግማሽ ነው ይዤልሃለሁ 🙏" → 01+ ይመዘግባል

ሰው: "21 31 01"
Bot: "21 31 በሙሉ 01+ በግማሽ ይዤልሃለሁ 🙏"
```

---

## 💳 የክፍያ System

### Flow
```
ሰው screenshot ይልካል
      ↓
Groq Vision Bot → ref number + telegram ID
      ↓
DB ያስቀምጣል
      ↓
SMS forward → URL/DB → ref + ብር match
      ↓
Approve → group ላይ ይገባል
      ↓
Main AI → board ✅ ያስጨምራል
```

### AI ✅ Logic
```
ብር በቃ    → ✅ ያስጨምራል
ብር አልበቃም → "X ብር ቀርቷል ጨምር 🙏"
Admin "በግማሽ አርግ" → format ቀይሮ ✅
```

### ብር Calculation
```
የመጣ ብር ÷ slot ዋጋ = ስንት slot ይሸፍናል
AI context ተረድቶ ትክክለኛውን ያርማል
```

---

## ⚠️ ያልከፈሉ ማስጠንቀቂያ

ሁሉም slots ሲሞሉ AI ያልከፈሉ ይፈልጋል:

```
⚠️ 2 ደቂቃ ይቀራል! ያልከፈሉ:
01
21
51+   ← ግማሽ ብቻ ያልከፈለ
```

### Rules
- ሙሉ ካልከፈለ → `01`
- ግማሽ ካልከፈለ → `01+`
- 2 ሰው ሁለቱም ካልከፈሉ → `01`
- 2 ሰው አንዱ ከፈለ → `01+`
- ሁለቱም ከፈሉ → ይጠፋል
- 2 ደቂቃ አልፎ ካልከፈለ → slot ይክፈታል
- ✅ approve ከሆነ → አይነካም

---

## 🏆 ውጤት እና አዲስ Game

```
Admin photo/video ይልካል (ዕጣ ውጤት)
      ↓
Groq Vision → ቁጥሮች ያነባል (1ኛ፣ 2ኛ፣ 3ኛ)
      ↓
Bot ያወጃል → DB ያስቀምጣል
      ↓
AI አዲስ board ይሰቅላል
```

**AI ማወቅ ያለበት:** ማን አሸነፈ ብቻ — ሂሳብ አይሠራም

---

## 🏅 Winner Balance System

### Formula
```
winner balance = prize - admin የላከው
```

### Admin እንዴት ያሳውቃል
```
1=3800
2=0
3=400
```

### Balance Logic
```
balance > 0  → እስከ balance ✅ auto
balance = 0  → slot ቢይዝ ✅ ያጠፋል
ቀሪ ✅ ብቻ ይጠፋል — slot እና ስም አይጠፋም!
```

### ምሳሌዎች
```
1ኛ prize=5,000 | admin 3,800 ላከ
balance = 5,000 - 3,800 = 1,200
→ እስከ 1,200ብር slots ✅ auto
→ 1,200 ካለፈ → ✅ ያጠፋል
→ admin ቀሪ 1,200 ሲልክ → ✅ ይቀጥላል

1ኛ prize=5,000 | admin 4,200 ላከ | winner 1,000 ይዞ ነበር
balance = 5,000 - 4,200 = 800
1,000 - 800 = 200 ትርፍ
→ 800✅ ይቆያል | 200✅ ብቻ ይጠፋል

winner 200 ከፍሎ ነበር + admin 4,200 ላከ
total = 200 + (5,000-4,200) = 1,000
→ 1,000 = 1,000 → ሁሉም ✅ ይቆያሉ
```

### ❓ ምልክት — 200ብር ቀሪ Reminder
```
01# አበበ ✅?  → አበበ ሙሉ ይዟል ግን 200 ብቻ ከፍሏል
             → 200 ቀሪ አለበት
             → ሌላ ግማሽ ቢጨምር → ✅ ይሆናል
```

---

## 🔄 Slot መቀየር

### Payment ሳይኖር
```
01 አበበ → 06 አበበ (ቀጥታ)
```

### Payment ካለ
```
01 አበበ ✅ → 06 አበበ ✅
01 አበበ ✅ → 06✅ + 11✅ (ብዙ ቢቀየር ✅ ይከፋፈላል)
```

### ቀሪ 200ብር ካለ
```
01 አበበ ✅+ 11 ቢቀየር → አበበ ✅+
ሌላ ግማሽ ቢጨምር → ✅ ይታረማል
```

---

## 🏗️ System Architecture

```
Python game_logic.py (አንተ rules ትጽፋለህ)
      ↓
trainer.py — 5,000+ synthetic games ይሠራል
      ↓
PostgreSQL (Neon) — data ይቀመጣል
      ↓
Groq Bot — screenshot vision + ዕጣ photo
      ↓
Main AI (DeepSeek/any) — board management + responses
```

---

## 📁 File Structure

```
lottery-ai/
├── config.py        # Variables + API rotation
├── game_logic.py    # Game rules
├── trainer.py       # 5,000+ synthetic data generator
└── .env             # Tokens, API keys, game config
```

## 🗄️ Database — PostgreSQL (Neon)

```
DATABASE_URL=postgresql://user:pass@ep-xxx.neon.tech/dbname
```

**Node.js:**
```bash
npm install pg dotenv
```

**Python:**
```bash
pip install psycopg2-binary python-dotenv
```
