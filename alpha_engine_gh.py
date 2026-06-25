"""Alpha Engine Pro - Token Insider Intelligence + Bundle Detector
   Jalan gratis 24/7 via GitHub Actions
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
DEX_PROFILES = "https://api.dexscreener.com/token-profiles/latest/v1"
DEX_PAIRS = "https://api.dexscreener.com/latest/dex/tokens/{addr}"
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")
SOLANA_RPC = "https://api.mainnet-beta.solana.com"

def load_seen():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            return set(json.load(f))
    return set()

def save_seen(seen):
    with open(TOKEN_FILE, "w") as f:
        json.dump(sorted(seen), f)

# ─── Deployer Quality ──────────────────────────────────────────
def deployer_quality(chain, dex, liq, age):
    dl = (dex or "").lower().strip()
    top = {"uniswap","raydium","raydium clmm","meteora","orca","orca whirlpool"}
    if dl in top:    base=60; badge="PRO"
    elif dl in {"pumpswap","raydium v4"}: base=40; badge="GRAD"
    elif dl in {"pumpfun","pump fun"}:    base=20; badge="BOND"
    else: base=30; badge="DEX"
    r = f"{badge}:{dex or '?'}"
    if liq and liq>50000: base+=20; r+=",liq50K"
    elif liq and liq>10000: base+=10; r+=",liq10K"
    return min(100,max(0,base)), badge, r

# ─── Solana On-Chain Check ────────────────────────────────────
async def check_solana_contract(session, addr):
    """Cek contract safety + holder concentration + bundle detection"""
    result = {"safety": {}, "holders": {}, "bundle": {}}
    if not addr or addr.startswith("0x"): return result
    
    try:
        # 1. Token info (mint/freeze authority)
        payload = {"jsonrpc":"2.0","id":1,"method":"getDigitalAsset","params":[addr]}
        # Try Token Extensions / Token-2022
        async with session.post(SOLANA_RPC, json={"jsonrpc":"2.0","id":1,"method":"getAccountInfo",
            "params":[addr,{"encoding":"jsonParsed"}]}, timeout=aiohttp.ClientTimeout(total=6)) as r:
            if r.status==200:
                data=await r.json()
                info=data.get("result",{}).get("value",{}).get("data",{}).get("parsed",{}).get("info",{})
                # Check authorities
                mint_auth = info.get("mintAuthority") or info.get("mint_authority")
                freeze_auth = info.get("freezeAuthority") or info.get("freeze_authority")
                result["safety"]["mint_auth"] = "YES" if mint_auth and mint_auth != "None" else "RENOUNCED"
                result["safety"]["freeze_auth"] = "YES" if freeze_auth and freeze_auth != "None" else "RENOUNCED"
                
                # Check token extensions (extensions field)
                extensions = info.get("extensions",[])
                if isinstance(extensions,list):
                    for ext in extensions:
                        if isinstance(ext,dict):
                            ename = ext.get("extension","")
                            if "mint" in ename.lower() and "authority" in ename.lower():
                                result["safety"]["mint_auth"] = "YES (ext)"
                            if "freeze" in ename.lower():
                                result["safety"]["freeze_auth"] = "YES (ext)"
    except: pass

    try:
        # 2. Top holders (bundle detection)
        async with session.post(SOLANA_RPC, json={"jsonrpc":"2.0","id":1,"method":"getTokenLargestAccounts",
            "params":[addr]}, timeout=aiohttp.ClientTimeout(total=6)) as r:
            if r.status==200:
                data=await r.json()
                accounts=data.get("result",{}).get("value",[])
                if accounts:
                    total=sum(a.get("uiAmount",0) or 0 for a in accounts[:10])
                    holder_data=[]
                    top10_pct=0
                    for a in accounts[:10]:
                        amt=a.get("uiAmount",0) or 0
                        pct=round(amt/total*100,1) if total>0 else 0
                        top10_pct+=pct
                        holder_data.append({"addr":a.get("address","")[:8],"pct":pct})
                    
                    result["holders"]["top10_pct"]=round(top10_pct,1)
                    result["holders"]["top10"]=holder_data
                    
                    # Insider signal: top 10 > 50% = very concentrated
                    if top10_pct>80: result["bundle"]["risk"]="🚨 EXTREME"
                    elif top10_pct>60: result["bundle"]["risk"]="⚠️ HIGH"
                    elif top10_pct>40: result["bundle"]["risk"]="👀 WATCH"
                    else: result["bundle"]["risk"]="✅ HEALTHY"
                    result["bundle"]["top10_pct"]=round(top10_pct,1)
    except: pass

    try:
        # 3. Check if deploy wallet funded multiple token holders
        # Get first few holder wallets to trace
        async with session.post(SOLANA_RPC, json={"jsonrpc":"2.0","id":1,"method":"getTokenLargestAccounts",
            "params":[addr]}, timeout=aiohttp.ClientTimeout(total=6)) as r:
            if r.status==200:
                data=await r.json()
                accounts=data.get("result",{}).get("value",[])
                # Check top 3 non-AMM holders for common funder
                top_wallets=[]
                for a in accounts[:5]:
                    w=a.get("address","")
                    if w: top_wallets.append(w)
                
                # Check first signatures of each wallet for common source
                funders={}
                for w_addr in top_wallets[:3]:
                    if not w_addr: continue
                    async with session.post(SOLANA_RPC, json={"jsonrpc":"2.0","id":1,
                        "method":"getSignaturesForAddress","params":[w_addr,{"limit":3}]},
                        timeout=aiohttp.ClientTimeout(total=4)) as sr:
                        if sr.status==200:
                            sigs=(await sr.json()).get("result",[])
                            for sig in sigs[:1]:  # Check first tx
                                tx_sig=sig.get("signature","")
                                if tx_sig:
                                    async with session.post(SOLANA_RPC, json={"jsonrpc":"2.0",
                                        "id":1,"method":"getTransaction","params":[tx_sig,{"encoding":"jsonParsed","maxSupportedTransactionVersion":0}]},
                                        timeout=aiohttp.ClientTimeout(total=4)) as tr:
                                        if tr.status==200:
                                            tx_data=(await tr.json()).get("result",{})
                                            accounts2=tx_data.get("transaction",{}).get("message",{}).get("accountKeys",[])
                                            if len(accounts2)>0:
                                                fee_payer=accounts2[0].get("pubkey","")
                                                if fee_payer:
                                                    funders[fee_payer[:12]]=funders.get(fee_payer[:12],0)+1
                
                # If 2+ wallets share the same funder = bundle
                shared=[f for f,c in funders.items() if c>=2]
                if shared:
                    result["bundle"]["detected"]=True
                    result["bundle"]["funder"]=shared[0]
                    result["bundle"]["count"]=max(funders.values())
                else:
                    result["bundle"]["detected"]=False
    except: pass

    return result

# ─── Scoring ────────────────────────────────────────────────────
def score_token(profile, pairs, chain_data=None):
    s={"score":0,"reasons":[],"details":{}}
    links=profile.get("links",[])
    if any(l.get("type")=="twitter" for l in links): s["score"]+=15; s["reasons"].append("twitter")
    if any(l.get("type")=="telegram" for l in links): s["score"]+=15; s["reasons"].append("telegram")
    if any("http" in l.get("url","") for l in links): s["score"]+=10; s["reasons"].append("website")
    desc=(profile.get("description") or "").strip()
    if len(desc)>20: s["score"]+=10; s["reasons"].append("deskripsi")
    elif len(desc)>0: s["score"]+=5; s["reasons"].append("ada_desc")
    else: s["score"]-=5; s["reasons"].append("no_desc")
    if profile.get("icon"): s["score"]+=5; s["reasons"].append("icon")
    if profile.get("header"): s["score"]+=5; s["reasons"].append("header")
    if profile.get("cto"): s["score"]-=20; s["reasons"].append("CTO!")
    updated=profile.get("updatedAt","")
    if updated:
        try:
            t=datetime.fromisoformat(updated.replace("Z","+00:00"))
            age=(datetime.now(timezone.utc)-t).total_seconds()/3600
            if age<1: s["score"]+=20; s["reasons"].append("baru")
            elif age<3: s["score"]+=10; s["reasons"].append("<3jam")
            s["details"]["age"]=round(age,1)
        except: pass
    if pairs:
        best=None
        for p in pairs:
            liq=float((p.get("liquidity") or {}).get("usd",0)) if isinstance(p.get("liquidity"),dict) else 0
            vol=float((p.get("volume") or {}).get("h24",0)) if isinstance(p.get("volume"),dict) else 0
            buys=sells=0
            txns=p.get("txns")
            if isinstance(txns,dict):
                h24=txns.get("h24")
                if isinstance(h24,dict): buys=int(h24.get("buys",0)); sells=int(h24.get("sells",0))
            if best is None or liq>best["liq"]:
                best={"liq":liq,"vol":vol,"price":float(p.get("priceUsd",0)or 0),
                      "buys":buys,"sells":sells,"dex":p.get("dexId","?"),"url":p.get("url","")}
        if best:
            for k,v in best.items(): s["details"][k]=v
            if best["liq"]>50000: s["score"]+=25; s["reasons"].append("liq50K")
            elif best["liq"]>10000: s["score"]+=15; s["reasons"].append("liq10K")
            elif best["liq"]>5000: s["score"]+=10; s["reasons"].append("liq5K")
            else: s["score"]-=5; s["reasons"].append("liq<5K")
            if best["vol"]>0 and best["liq"]>0:
                r=best["vol"]/best["liq"]
                if r>10: s["score"]+=25; s["reasons"].append("vol_gila!")
                elif r>5: s["score"]+=20; s["reasons"].append("vol_gila")
                elif r>2: s["score"]+=10; s["reasons"].append("vol_sehat")
                s["details"]["vol_liq"]=round(r,2)
            total_tx=best["buys"]+best["sells"]
            if total_tx>10:
                bp=(best["buys"]/total_tx)*100
                s["details"]["buy_pct"]=round(bp,1)
                if bp>80: s["score"]+=20; s["reasons"].append("accumulation!")
                elif bp<30: s["score"]-=15; s["reasons"].append("dumping!")
    
    # Deployer quality
    dex_n=best["dex"] if best else "?"
    liq_v=best["liq"] if best else 0
    dq,dqb,dqr=deployer_quality(profile.get("chainId","?"),dex_n,liq_v,s["details"].get("age"))
    s["details"]["dep_score"]=dq; s["details"]["dep_badge"]=dqb; s["details"]["dep_reason"]=dqr
    if dq>=80: s["score"]+=30; s["reasons"].append(f"deployer_PRO({dq})")
    elif dq>=60: s["score"]+=25; s["reasons"].append(f"deployer_{dqb}({dq})")
    elif dq>=40: s["score"]+=15; s["reasons"].append(f"deployer_{dqb}({dq})")
    elif dq>=20: s["score"]+=5; s["reasons"].append(f"deployer_bond({dq})")
    
    # ─── INSIDER PRO FEATURES ─────────────────────────────────
    if chain_data:
        safety=chain_data.get("safety",{})
        bundle=chain_data.get("bundle",{})
        holders=chain_data.get("holders",{})
        
        # Contract safety
        ma=safety.get("mint_auth","")
        fa=safety.get("freeze_auth","")
        if "RENOUNCED" in str(ma): s["score"]+=15; s["reasons"].append("mint_renounced✅")
        elif ma: s["score"]-=20; s["reasons"].append(f"mint_active⚠️")
        if "RENOUNCED" in str(fa): s["score"]+=5; s["reasons"].append("freeze_renounced")
        elif fa: s["score"]-=10; s["reasons"].append("freeze_active⚠️")
        s["details"]["mint_auth"]=str(ma) if ma else "?"
        s["details"]["freeze_auth"]=str(fa) if fa else "?"
        
        # Bundle / Holder concentration
        bundle_risk=bundle.get("risk","")
        if bundle_risk=="✅ HEALTHY": s["score"]+=20; s["reasons"].append("holders_sehat")
        elif bundle_risk=="👀 WATCH": s["score"]+=0; s["reasons"].append("holders_terpusat")
        elif bundle_risk=="⚠️ HIGH": s["score"]-=15; s["reasons"].append("holders_sangat_terpusat⚠️")
        elif bundle_risk=="🚨 EXTREME": s["score"]-=30; s["reasons"].append("INSIDER_ALERT🚨")
        s["details"]["bundle_risk"]=bundle_risk
        
        if bundle.get("detected"):
            s["score"]-=20; s["reasons"].append("BUNDLE_DETECTED🚨")
            s["details"]["bundle_detected"]=True
        else:
            s["details"]["bundle_detected"]=False
        
        # Holder concentration
        top10=holders.get("top10_pct",0)
        s["details"]["top10_pct"]=top10
    
    s["score"]=max(0,min(100,s["score"]))
    return s

async def main():
    seen=load_seen()
    out=[]; alerts=[]
    out.append(f"\n{'='*55}"); out.append(f"  ALPHA ENGINE PRO — Insider Intel")
    out.append(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    out.append(f"{'='*55}\n")

    async with aiohttp.ClientSession() as session:
        async with session.get(DEX_PROFILES,headers={"User-Agent":"Mozilla/5.0"},
                                timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status!=200: out.append("Gagal fetch!"); print("\n".join(out)); return
            profiles=await r.json()
        out.append(f"Scan {len(profiles)} profiles\n")
        new_addrs=set(); scored=[]

        for p in profiles:
            addr=p.get("tokenAddress","")
            if not addr or addr in seen: continue
            new_addrs.add(addr); chain=p.get("chainId","?")
            pairs_data=None
            async with session.get(DEX_PAIRS.format(addr=addr),headers={"User-Agent":"Mozilla/5.0"},
                                    timeout=aiohttp.ClientTimeout(total=8)) as pr:
                if pr.status==200: pairs_data=await pr.json()
            pairs=pairs_data.get("pairs",[]) if pairs_data else []
            symbol=pairs[0].get("baseToken",{}).get("symbol","?") if pairs else "?"
            
            # On-chain check for Solana
            chain_data=None
            if chain=="solana" and not addr.startswith("0x"):
                out.append(f"  🔍 {symbol}: on-chain check...")
                chain_data=await check_solana_contract(session, addr)
                
                # Show safety
                if chain_data:
                    s=chain_data.get("safety",{})
                    b=chain_data.get("bundle",{})
                    h=chain_data.get("holders",{})
                    ma=s.get("mint_auth","?")
                    br=b.get("risk","?")
                    hp=h.get("top10_pct","?")
                    if chain_data.get("bundle",{}).get("detected"):
                        out.append(f"     Bundle: 🚨 DETECTED! Top10: {hp}% Holder: {br}")
                    else:
                        out.append(f"     Mint:{ma} Top10:{hp}% {br}")
            
            result=score_token(p,pairs,chain_data)
            result["addr"]=addr; result["chain"]=chain; result["symbol"]=symbol
            scored.append(result)
            dep_s=result["details"].get("dep_score",0)
            bundle_r=result["details"].get("bundle_risk","")
            b_icon="🚨" if "EXTREME" in str(bundle_r) else "⚠️" if "HIGH" in str(bundle_r) else ""
            icon=" 👑" if dep_s>=60 else " 🐣" if dep_s<=10 else ""
            out.append(f"  {symbol:12s} S:{result['score']:2d} D:{dep_s:3.0f}{icon} {b_icon}")

        if not scored:
            out.append("\nTidak ada token baru.")
            seen|=new_addrs; save_seen(seen); print("\n".join(out)); return

        scored.sort(key=lambda x:x["score"],reverse=True)
        out.append(f"\n{'='*55}"); out.append(f"  RANKING")
        out.append(f"{'='*55}\n")

        for s in scored[:10]:
            lab="GOLD" if s["score"]>=80 else "SILVER" if s["score"]>=60 else "BRONZE" if s["score"]>=40 else "WATCH"
            sym,chain,addr=s["symbol"],s["chain"],s["addr"]
            price=s["details"].get("price",0); liq=s["details"].get("liq",0)
            vol_l=s["details"].get("vol_liq"); dex=s["details"].get("dex","?")
            buys=s["details"].get("buys",0); sells=s["details"].get("sells",0)
            bp=s["details"].get("buy_pct")
            dep_b=s["details"].get("dep_badge","?"); dep_s2=s["details"].get("dep_score",0)
            dep_r=s["details"].get("dep_reason","")
            br=s["details"].get("bundle_risk","")
            ma=s["details"].get("mint_auth","?")
            fa=s["details"].get("freeze_auth","?")
            tp=s["details"].get("top10_pct","?")
            
            anomaly=""
            if bp:
                            if bp>80: anomaly=" ACCUM"
                            elif bp<30: anomaly=" DUMPING"
            price_s=f"${price:.8f}" if price<1 else f"${price:.4f}"
            liq_s=f"${liq:,.0f}" if liq else "?"
            
            out.append(f"  {lab}{anomaly}  {sym}  {price_s}  Liq:{liq_s}")
            out.append(f"    Vol/Liq:{vol_l}x B:{buys}S:{sells}" if vol_l else "")
            out.append(f"    {dex} D:{dep_b}({dep_s2}) {dep_r}")
            # Insider pro details
            pro_line=[]
            if br: pro_line.append(f"Holder:{br}({tp}%)")
            if ma and ma!="?": pro_line.append(f"Mint:{ma}")
            if chain=="solana": pro_line.append(f"Freeze:{fa}")
            if pro_line: out.append(f"    {' | '.join(pro_line)}")
            out.append(f"    https://dexscreener.com/{chain}/{addr}")
            out.append("")
            if s["score"]>=60: alerts.append(s)

        seen|=new_addrs; save_seen(seen)
        out.append(f"{len(scored)} scanned, {len(alerts)} alerts")

    # Telegram
    if alerts and TG_BOT_TOKEN and TG_CHAT_ID:
        async with aiohttp.ClientSession() as tg:
            for s in alerts:
                sym,chain,addr=s["symbol"],s["chain"],s["addr"]
                price=s["details"].get("price",0); liq=s["details"].get("liq",0)
                reasons=", ".join(s["reasons"][:3])
                dep_s2=s["details"].get("dep_score",0)
                dep_r=s["details"].get("dep_reason","")
                br=s["details"].get("bundle_risk","")
                ma=s["details"].get("mint_auth","?")
                emoji="PRO" if dep_s2>=80 else "OK" if dep_s2>=60 else "BOND"
                safety=""
                if "RENOUNCED" in str(ma): safety="🛡️"
                elif ma: safety="⚠️"
                
                msg=f"Alpha: {sym} ({s['score']}/100 {emoji}{safety})\n"
                msg+=f"${liq:,.0f} liq | ${price:.8f}\n{reasons} | {dep_r}\n"
                if br: msg+=f"Holder: {br} | Mint: {ma}\n"
                msg+=f"https://dexscreener.com/{chain}/{addr}"
                if chain=="solana": msg+=f"\nhttps://jup.ag/swap/{addr}-USDC"
                async with tg.post(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
                                    json={"chat_id":TG_CHAT_ID,"text":msg}) as resp:
                    await resp.read()
        out.append("Telegram sent!")
    print("\n".join(out))

if __name__=="__main__":
    asyncio.run(main())