"""Alpha Engine for GitHub Actions - Token Insider Intelligence
   Jalan gratis 24/7, commit seen_tokens.json biar ga re-alert
"""
import asyncio, json, os, sys
from datetime import datetime, timezone

try:
    import aiohttp
except ImportError:
    os.system(f"{sys.executable} -m pip install aiohttp -q")
    import aiohttp

# ─── Config ─────────────────────────────────────────────────────
TOKEN_FILE = "seen_tokens.json"
DEXSCREENER_PROFILES = "https://api.dexscreener.com/token-profiles/latest/v1"
DEXSCREENER_PAIRS = "https://api.dexscreener.com/latest/dex/tokens/{addr}"
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")

def load_seen():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            return set(json.load(f))
    return set()

def save_seen(seen):
    with open(TOKEN_FILE, "w") as f:
        json.dump(sorted(seen), f)

# ─── Deployer Quality ──────────────────────────────────────────
def get_deployer_quality(chain, dex, liq, age_hours):
    dex_lower = (dex or "").lower().strip()
    top_dex = {"uniswap", "raydium", "raydium clmm", "raydium cpmm",
               "meteora", "meteora dlmm", "meteora damm v2",
               "orca", "orca whirlpool", "orca wavebreak"}
    grad_dex = {"pumpswap", "raydium v4"}
    bonding_dex = {"pumpfun", "pump fun"}
    
    if dex_lower in top_dex:
        base = 60; badge = "PRO"
    elif dex_lower in grad_dex:
        base = 40; badge = "GRAD"
    elif dex_lower in bonding_dex:
        base = 20; badge = "BOND"
    else:
        base = 30; badge = "DEX"
    
    reason = f"{badge}: {dex or '?'}"
    if liq and liq > 50000:     base += 20; reason += ", liq>50K"
    elif liq and liq > 10000:   base += 10; reason += ", liq>10K"
    if chain in ("ethereum","base","bsc","arbitrum","polygon"):
        base += 5; reason += ", evm"
    return min(100, max(0, base)), badge, reason

# ─── Scoring ────────────────────────────────────────────────────
def score_token(profile, pairs):
    s = {"score": 0, "reasons": [], "details": {}}
    links = profile.get("links", [])
    has_tw = any(l.get("type")=="twitter" for l in links)
    has_tg = any(l.get("type")=="telegram" for l in links)
    has_site = any("http" in l.get("url","") for l in links)
    if has_tw: s["score"]+=15; s["reasons"].append("twitter")
    if has_tg: s["score"]+=15; s["reasons"].append("telegram")
    if has_site: s["score"]+=10; s["reasons"].append("website")
    desc = (profile.get("description") or "").strip()
    if len(desc)>20:    s["score"]+=10; s["reasons"].append("deskripsi")
    elif len(desc)>0:   s["score"]+=5;  s["reasons"].append("ada_desc")
    else:               s["score"]-=5;  s["reasons"].append("no_desc")
    if profile.get("icon"):   s["score"]+=5;  s["reasons"].append("icon")
    if profile.get("header"): s["score"]+=5;  s["reasons"].append("header")
    if profile.get("cto"):    s["score"]-=20; s["reasons"].append("CTO!")
    updated = profile.get("updatedAt","")
    if updated:
        try:
            t = datetime.fromisoformat(updated.replace("Z","+00:00"))
            age = (datetime.now(timezone.utc)-t).total_seconds()/3600
            if age<1:       s["score"]+=20; s["reasons"].append("baru")
            elif age<3:     s["score"]+=10; s["reasons"].append("<3jam")
            elif age<6:     s["score"]+=5;  s["reasons"].append("<6jam")
            s["details"]["age"] = round(age,1)
        except: pass
    # Pair data
    if pairs:
        best = None
        for p in pairs:
            liq = float((p.get("liquidity") or {}).get("usd",0)) if isinstance(p.get("liquidity"),dict) else 0
            vol = float((p.get("volume") or {}).get("h24",0)) if isinstance(p.get("volume"),dict) else 0
            buys=sells=0
            txns=p.get("txns")
            if isinstance(txns,dict):
                h24=txns.get("h24")
                if isinstance(h24,dict):
                    buys=int(h24.get("buys",0))
                    sells=int(h24.get("sells",0))
            if best is None or liq > best["liq"]:
                best={"liq":liq,"vol":vol,"price":float(p.get("priceUsd",0)or 0),
                      "buys":buys,"sells":sells,"dex":p.get("dexId","?"),"url":p.get("url","")}
        if best:
            for k,v in best.items(): s["details"][k]=v
            if best["liq"]>50000:   s["score"]+=25; s["reasons"].append("liq>50K")
            elif best["liq"]>10000: s["score"]+=15; s["reasons"].append("liq>10K")
            elif best["liq"]>5000:  s["score"]+=10; s["reasons"].append("liq>5K")
            else:                   s["score"]-=5;  s["reasons"].append("liq<5K")
            if best["vol"]>0 and best["liq"]>0:
                ratio = best["vol"]/best["liq"]
                if ratio>10: s["score"]+=25; s["reasons"].append("volume_gila!")
                elif ratio>5: s["score"]+=20; s["reasons"].append("vol_gila")
                elif ratio>2: s["score"]+=10; s["reasons"].append("vol_sehat")
                s["details"]["vol_liq"]=round(ratio,2)
            total_tx = best["buys"]+best["sells"]
            if total_tx>10:
                buy_pct = (best["buys"]/total_tx)*100
                s["details"]["buy_pct"]=round(buy_pct,1)
                if buy_pct>80:    s["score"]+=20; s["reasons"].append("accumulation!")
                elif buy_pct>65:  s["score"]+=10; s["reasons"].append("buy_side")
                elif buy_pct<30:  s["score"]-=15; s["reasons"].append("dumping!")
                elif buy_pct<45:  s["score"]-=5;  s["reasons"].append("sell_side")
    # Deployer quality
    dex_name = best["dex"] if best else "?"
    liq_val = best["liq"] if best else 0
    age_h = s["details"].get("age")
    dq_score, dq_badge, dq_reason = get_deployer_quality(profile.get("chainId","?"), dex_name, liq_val, age_h)
    s["details"]["dep_score"]=dq_score
    s["details"]["dep_badge"]=dq_badge
    s["details"]["dep_reason"]=dq_reason
    if dq_score>=80:    s["score"]+=30; s["reasons"].append(f"deployer_PRO({dq_score})")
    elif dq_score>=60:  s["score"]+=25; s["reasons"].append(f"deployer_{dq_badge}({dq_score})")
    elif dq_score>=40:  s["score"]+=15; s["reasons"].append(f"deployer_{dq_badge}({dq_score})")
    elif dq_score>=20:  s["score"]+=5;  s["reasons"].append(f"deployer_bond({dq_score})")
    s["score"]=max(0, min(100, s["score"]))
    return s

async def main():
    seen = load_seen()
    out = []
    out.append(f"\n{'='*55}")
    out.append(f"  ALPHA ENGINE — GitHub Actions")
    out.append(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    out.append(f"{'='*55}\n")

    async with aiohttp.ClientSession() as session:
        async with session.get(DEXSCREENER_PROFILES, headers={"User-Agent": "Mozilla/5.0"},
                                timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status != 200:
                out.append("Gagal fetch token profiles!")
                print("\n".join(out)); return
            profiles = await r.json()
        out.append(f"Scan {len(profiles)} profiles\n")

        new_addrs = set()
        scored = []
        for p in profiles:
            addr = p.get("tokenAddress","")
            if not addr or addr in seen: continue
            new_addrs.add(addr)
            chain = p.get("chainId","?")
            pairs_data = None
            async with session.get(DEXSCREENER_PAIRS.format(addr=addr),
                                    headers={"User-Agent": "Mozilla/5.0"},
                                    timeout=aiohttp.ClientTimeout(total=8)) as pr:
                if pr.status == 200: pairs_data = await pr.json()
            pairs = pairs_data.get("pairs",[]) if pairs_data else []
            symbol = pairs[0].get("baseToken",{}).get("symbol","?") if pairs else "?"
            result = score_token(p, pairs)
            result["addr"]=addr; result["chain"]=chain; result["symbol"]=symbol
            scored.append(result)
            dep_s = result["details"].get("dep_score",0)
            icon = " 👑" if dep_s>=60 else " 🐣" if dep_s<=10 else ""
            out.append(f"  {symbol:12s} {chain:10s} Score:{result['score']:2d} D:{dep_s:3.0f}{icon}")

        if not scored:
            out.append("\nTidak ada token baru.")
            seen |= new_addrs; save_seen(seen)
            print("\n".join(out)); return

        scored.sort(key=lambda x: x["score"], reverse=True)
        out.append(f"\n{'='*55}")
        out.append(f"  RANKING")
        out.append(f"{'='*55}\n")

        alerts = []
        for s in scored[:10]:
            lab = "GOLD" if s["score"]>=80 else "SILVER" if s["score"]>=60 else "BRONZE" if s["score"]>=40 else "WATCH"
            sym, chain, addr = s["symbol"], s["chain"], s["addr"]
            price = s["details"].get("price",0)
            liq = s["details"].get("liq",0)
            vol_l = s["details"].get("vol_liq")
            dex = s["details"].get("dex","?")
            buys = s["details"].get("buys",0)
            sells = s["details"].get("sells",0)
            bp = s["details"].get("buy_pct")
            dep_b = s["details"].get("dep_badge","?")
            dep_s2 = s["details"].get("dep_score",0)
            dep_r = s["details"].get("dep_reason","")
            reasons = ", ".join(s["reasons"][:4])
            anomaly = ""
            if bp:
                if bp>80: anomaly=" ACCUM"
                elif bp>65: anomaly=" BUY>SELL"
                elif bp<30: anomaly=" DUMPING"
            price_s = f"${price:.8f}" if price<1 else f"${price:.4f}"
            liq_s = f"${liq:,.0f}" if liq else "?"
            out.append(f"  {lab}{anomaly}  {sym}  {price_s}  Liq:{liq_s}")
            if vol_l: out.append(f"    Vol/Liq:{vol_l}x  B:{buys} S:{sells}")
            out.append(f"    {dex}  D:{dep_b}({dep_s2})  {dep_r}")
            out.append(f"    https://dexscreener.com/{chain}/{addr}")
            out.append("")
            if s["score"]>=60: alerts.append(s)

        seen |= new_addrs; save_seen(seen)
        out.append(f"{len(scored)} scanned, {len(alerts)} alerts")

    if alerts and TG_BOT_TOKEN and TG_CHAT_ID:
        async with aiohttp.ClientSession() as tg:
            for s in alerts:
                sym, chain, addr = s["symbol"], s["chain"], s["addr"]
                price = s["details"].get("price",0)
                liq = s["details"].get("liq",0)
                reasons = ", ".join(s["reasons"][:3])
                dep_s2 = s["details"].get("dep_score",0)
                dep_r = s["details"].get("dep_reason","")
                emoji = "PRO" if dep_s2>=80 else "OK" if dep_s2>=60 else "BOND"
                msg = (
                    f"Alpha: {sym} ({s['score']}/100 {emoji})\n"
                    f"${liq:,.0f} liq | ${price:.8f}\n"
                    f"{reasons} | {dep_r}\n"
                    f"https://dexscreener.com/{chain}/{addr}"
                )
                if chain=="solana":
                    msg += f"\nhttps://jup.ag/swap/{addr}-USDC"
                async with tg.post(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
                                    json={"chat_id":TG_CHAT_ID,"text":msg}) as resp:
                    await resp.read()
        out.append("Telegram sent!")

    print("\n".join(out))

if __name__ == "__main__":
    asyncio.run(main())