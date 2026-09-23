# 🎮 BGMI Describe Bot — @ListoAIbot

BGMI account screenshots bhejo → structured listing milegi automatically.

**Detects:** Gun Skins 🔫 · Outfits 🎽 · Vehicles 🚘 · Helmets/Bags 🎒 · Stats ⛔️

---

## 📁 File Structure

```
bgmi-bot/
├── bot.py           ← Main bot logic
├── prompt.py        ← AI prompt + listing formatter
├── requirements.txt ← Python dependencies
├── Procfile         ← Railway deployment config
└── README.md        ← This file
```

---

## 🚀 Railway Deployment (Step by Step)

### Step 1 — Bot Token lao (BotFather se)

1. Telegram pe `@BotFather` open karo
2. `/newbot` type karo
3. Bot ka naam do: `BGMI Describe Bot`
4. Username do: `ListoAIbot`
5. **Bot Token copy kar lo** — yeh baad mein chahiye

### Step 2 — OpenRouter API Key lao

1. [openrouter.ai](https://openrouter.ai) pe account banao
2. Dashboard → **Keys** → `Create Key`
3. **API Key copy kar lo**

### Step 3 — GitHub pe code daalo

1. GitHub pe new repository banao (private rakho)
2. Yeh saare files upload karo:
   - `bot.py`
   - `prompt.py`
   - `requirements.txt`
   - `Procfile`

### Step 4 — Railway pe deploy karo

1. [railway.app](https://railway.app) pe jao → **Login with GitHub**
2. **New Project** → `Deploy from GitHub repo`
3. Apni repository select karo
4. Railway automatically code detect karega

### Step 5 — Environment Variables set karo

Railway Dashboard → Apna project → **Variables** tab → yeh 3 variables add karo:

| Variable Name      | Value                                              |
|--------------------|----------------------------------------------------|
| `TELEGRAM_BOT_TOKEN` | `123456:ABCdef...` (BotFather se mila token)    |
| `OPENROUTER_API_KEY` | `sk-or-...` (OpenRouter se mila key)            |
| `OPENROUTER_MODEL`   | `meta-llama/llama-3.2-11b-vision-instruct:free` |

Variables save karne ke baad Railway automatically redeploy karega.

### Step 6 — Deploy Type set karo

Railway Dashboard → Settings → **Deploy** section:
- **Start Command:** `python bot.py`
- Ya Procfile already set hai, kuch karna nahi

### Step 7 — Check karo

1. Railway → **Logs** tab kholo
2. Yeh line dikhni chahiye:
   ```
   Starting BGMI Describe Bot (@ListoAIbot)
   Model: meta-llama/llama-3.2-11b-vision-instruct:free
   ```
3. Telegram pe apna bot open karo → `/start` bhejo
4. Ek BGMI screenshot bhejo → listing aa jayegi!

---

## 🤖 OpenRouter Models (Recommended)

| Model | Speed | Quality | Cost |
|-------|-------|---------|------|
| `meta-llama/llama-3.2-11b-vision-instruct:free` | Fast | Good | Free ✅ |
| `qwen/qwen-2-vl-7b-instruct:free` | Fast | Good | Free ✅ |
| `google/gemini-flash-1.5` | Very Fast | Very Good | Paid |
| `google/gemini-2.0-flash-exp:free` | Fast | Very Good | Free ✅ |
| `openai/gpt-4o` | Medium | Best | Paid |

**Model change karna:** Railway → Variables → `OPENROUTER_MODEL` update karo → auto redeploy

---

## 📋 Bot Commands

| Command  | Kya karta hai                    |
|----------|----------------------------------|
| `/start` | Welcome message                  |
| `/help`  | All commands + features          |
| `/model` | Current AI model name dikhata hai |

---

## 💬 Usage

**Single screenshot:**
- Ek photo bhejo → Bot analyze karega

**Multiple screenshots:**
- Multiple photos ek saath select karke bhejo (media group)
- Bot saari photos ek saath analyze karega
- Ek combined listing milegi

**Output format:**
```
#G0
[ GLACIER M416 ACCOUNT ]

➖ 45/300 Mythic Fashion

🎽 Arctic Set
🎽 Snow White Character

Upgradable Weapons:
🔫 Glacier M416 (Lv. 3)
🔫 Aurora AKM (Lv. 2)

⛔️ Account Level 71+
⛔️ Season Rank: Top 5%+

🎒 Arctic Helmet Skin
🎒 Snow Bag Skin

🚘 BRDM Snow Leopard

✍️ Price: 
✍️ Login: 
✍️ Dm To Buy: 
```

---

## 🔧 Troubleshooting

**Bot respond nahi kar raha?**
- Railway Logs check karo error ke liye
- `TELEGRAM_BOT_TOKEN` sahi hai?

**"AI API error" aa raha hai?**
- `OPENROUTER_API_KEY` sahi hai?
- OpenRouter account mein credits hain?
- Free model rate limit hit? — Thodi der baad try karo

**Listing galat aa rahi hai?**
- Better model try karo (e.g. `google/gemini-flash-1.5`)
- Clear screenshots bhejo, screenshots blur ya dark na hon

**Railway bot band ho gaya?**
- Railway Free plan mein $5 credit milta hai
- Usage khatam hone pe paid plan lena hoga (~$5/month for small bot)

---

## 📞 Personal Use Only

Yeh bot personal use ke liye hai — koi daily limits nahi, koi referral system nahi, koi database nahi. Sirf screenshot bhejo, listing pao.
