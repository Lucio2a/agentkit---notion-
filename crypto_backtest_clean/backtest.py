import csv
import importlib
import io
import math
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import requests


DATA_DIR = Path(__file__).resolve().parent / "data"
CSV_PATH = DATA_DIR / "btcusdt_5m_backtrader.csv"
EQUITY_CSV_PATH = DATA_DIR / "equity_curve.csv"
EQUITY_SVG_PATH = DATA_DIR / "equity_curve.svg"


@dataclass
class Candle:
    dt: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Trade:
    entry_dt: datetime
    exit_dt: datetime
    entry: float
    exit: float
    size: float
    pnl: float


@dataclass
class Results:
    final_capital: float
    winrate: float
    max_drawdown: float
    profit_factor: float
    total_trades: int



def check_and_install_packages():
    wanted = ["backtrader", "pandas", "numpy", "matplotlib", "requests"]
    missing = []
    for pkg in wanted:
        try:
            importlib.import_module(pkg)
        except ImportError:
            missing.append(pkg)

    print("Vérification des packages...")
    if not missing:
        print("✅ Tous les packages demandés sont installés.")
        return

    print(f"Packages manquants: {missing}")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
        print("✅ Installation terminée.")
    except Exception as exc:
        print("⚠️ Installation impossible dans cet environnement (proxy/réseau).")
        print(f"Détail: {exc}")
        print("⚠️ Je continue avec un moteur de backtest Python pur (sans dépendances externes).")



def iter_months_back(limit=36):
    cur = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    y, m = cur.year, cur.month
    for _ in range(limit):
        yield y, m
        m -= 1
        if m == 0:
            m = 12
            y -= 1



def download_data(min_days=365):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    rows = []

    for y, m in iter_months_back(36):
        ym = f"{y}-{m:02d}"
        url = f"https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/5m/BTCUSDT-5m-{ym}.zip"
        print(f"Téléchargement: {ym}")
        try:
            r = requests.get(url, timeout=30)
            if r.status_code != 200:
                continue
            with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
                for name in zf.namelist():
                    text = zf.read(name).decode("utf-8")
                    reader = csv.reader(io.StringIO(text))
                    for row in reader:
                        if not row:
                            continue
                        dt = datetime.utcfromtimestamp(int(row[0]) / 1000)
                        rows.append([
                            dt,
                            float(row[1]),
                            float(row[2]),
                            float(row[3]),
                            float(row[4]),
                            float(row[5]),
                        ])
        except Exception:
            continue

        if rows:
            rows_sorted = sorted(rows, key=lambda x: x[0])
            if (rows_sorted[-1][0] - rows_sorted[0][0]).days >= min_days:
                break

    if not rows:
        print("⚠️ Impossible de télécharger Binance (réseau). Génération de données de démonstration locales (1 an, 5m).")
        rows = generate_synthetic_rows(min_days=min_days)

    rows = sorted(rows, key=lambda x: x[0])
    end_dt = rows[-1][0]
    start_dt = end_dt - timedelta(days=min_days)
    rows = [r for r in rows if r[0] >= start_dt]

    with CSV_PATH.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["datetime", "open", "high", "low", "close", "volume"])
        for r in rows:
            w.writerow([r[0].strftime("%Y-%m-%d %H:%M:%S"), r[1], r[2], r[3], r[4], r[5]])

    print(f"✅ CSV compatible Backtrader créé: {CSV_PATH} ({len(rows)} lignes)")
    return [Candle(*r) for r in rows]



def generate_synthetic_rows(min_days=365):
    start = datetime.utcnow() - timedelta(days=min_days)
    total = int((min_days * 24 * 60) / 5)
    price = 30000.0
    out = []
    for i in range(total):
        dt = start + timedelta(minutes=5*i)
        drift = 0.00002
        wave = math.sin(i / 180.0) * 0.0012
        breakout = 0.0
        if i % 500 == 0:
            breakout = 0.01
        move = drift + wave + breakout
        new_price = max(1000.0, price * (1 + move))
        hi = max(price, new_price) * (1 + 0.0012)
        lo = min(price, new_price) * (1 - 0.0010)
        vol = 50 + 20 * abs(math.sin(i / 50.0)) + (120 if breakout > 0 else 0)
        out.append([dt, price, hi, lo, new_price, vol])
        price = new_price
    return out


def sma(values):
    return sum(values) / len(values) if values else 0.0



def stddev(values):
    if not values:
        return 0.0
    m = sma(values)
    return math.sqrt(sum((x - m) ** 2 for x in values) / len(values))



def ema(prev, value, period):
    alpha = 2 / (period + 1)
    return value if prev is None else (alpha * value + (1 - alpha) * prev)



def run_backtest(candles):
    capital = 10_000.0
    fee = 0.001

    position_size = 0.0
    entry_price = 0.0
    stop_price = 0.0
    tp1_price = 0.0
    tp1_hit = False

    trades = []
    gross_profit, gross_loss = 0.0, 0.0
    equity_curve = []

    prev_ema9 = None
    atr_values = []

    for i in range(len(candles)):
        c = candles[i]

        close_hist = [x.close for x in candles[max(0, i - 19): i + 1]]
        vol_hist = [x.volume for x in candles[max(0, i - 19): i + 1]]

        if i > 0:
            prev_close = candles[i - 1].close
            tr = max(c.high - c.low, abs(c.high - prev_close), abs(c.low - prev_close))
            atr_values.append(tr)

        atr14 = sma(atr_values[-14:]) if len(atr_values) >= 14 else None
        bb_mid = sma(close_hist) if len(close_hist) == 20 else None
        bb_std = stddev(close_hist) if len(close_hist) == 20 else None
        bb_upper = (bb_mid + 2 * bb_std) if bb_mid is not None else None
        vol_sma20 = sma(vol_hist) if len(vol_hist) == 20 else None
        prev_ema9 = ema(prev_ema9, c.close, 9)

        if position_size == 0 and i >= 30 and bb_upper and atr14 and vol_sma20:
            highest_10_prev = max(x.high for x in candles[i - 10:i])
            cond1 = c.close > bb_upper
            cond2 = c.volume > 1.3 * vol_sma20
            cond3 = c.close > highest_10_prev

            if cond1 and cond2 and cond3:
                stop_distance = 1.8 * atr14
                if stop_distance <= 0:
                    continue
                risk_amount = capital * 0.01
                qty = risk_amount / stop_distance
                qty = math.floor(qty * 1000) / 1000.0
                if qty <= 0:
                    continue

                entry_price = c.close
                position_size = qty
                stop_price = entry_price - stop_distance
                tp1_price = entry_price + stop_distance
                tp1_hit = False

                capital -= entry_price * position_size * fee

        elif position_size > 0:
            # SL prioritaire
            if c.low <= stop_price:
                exit_price = stop_price
                pnl = (exit_price - entry_price) * position_size
                pnl -= (entry_price * position_size + exit_price * position_size) * fee
                capital += pnl
                trades.append(Trade(c.dt, c.dt, entry_price, exit_price, position_size, pnl))
                if pnl >= 0:
                    gross_profit += pnl
                else:
                    gross_loss += abs(pnl)
                position_size = 0.0

            else:
                # TP1 50%
                if (not tp1_hit) and c.high >= tp1_price:
                    half = position_size / 2.0
                    pnl_half = (tp1_price - entry_price) * half
                    pnl_half -= (entry_price * half + tp1_price * half) * fee
                    capital += pnl_half
                    position_size -= half
                    tp1_hit = True
                    if pnl_half >= 0:
                        gross_profit += pnl_half
                    else:
                        gross_loss += abs(pnl_half)

                # trailing sous EMA9
                if tp1_hit and c.close < prev_ema9:
                    exit_price = c.close
                    pnl = (exit_price - entry_price) * position_size
                    pnl -= (entry_price * position_size + exit_price * position_size) * fee
                    capital += pnl
                    trades.append(Trade(c.dt, c.dt, entry_price, exit_price, position_size, pnl))
                    if pnl >= 0:
                        gross_profit += pnl
                    else:
                        gross_loss += abs(pnl)
                    position_size = 0.0

        floating = (c.close - entry_price) * position_size if position_size > 0 else 0.0
        equity_curve.append((c.dt, capital + floating))

    if position_size > 0:
        c = candles[-1]
        exit_price = c.close
        pnl = (exit_price - entry_price) * position_size
        pnl -= (entry_price * position_size + exit_price * position_size) * fee
        capital += pnl
        trades.append(Trade(c.dt, c.dt, entry_price, exit_price, position_size, pnl))
        if pnl >= 0:
            gross_profit += pnl
        else:
            gross_loss += abs(pnl)

    write_equity_outputs(equity_curve)

    wins = sum(1 for t in trades if t.pnl > 0)
    total = len(trades)
    winrate = (wins / total * 100) if total else 0.0

    peak = -1e18
    max_dd = 0.0
    for _, eq in equity_curve:
        peak = max(peak, eq)
        if peak > 0:
            dd = (peak - eq) / peak * 100
            max_dd = max(max_dd, dd)

    if gross_loss > 0:
        pf = gross_profit / gross_loss
    else:
        pf = float("inf") if gross_profit > 0 else 0.0

    return Results(capital, winrate, max_dd, pf, total)



def write_equity_outputs(equity_curve):
    with EQUITY_CSV_PATH.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["datetime", "equity"])
        for dt, eq in equity_curve:
            w.writerow([dt.strftime("%Y-%m-%d %H:%M:%S"), f"{eq:.2f}"])

    width, height = 1000, 400
    margin = 40
    vals = [v for _, v in equity_curve]
    if not vals:
        return
    mn, mx = min(vals), max(vals)
    span = (mx - mn) if (mx - mn) > 0 else 1.0

    points = []
    for i, (_, val) in enumerate(equity_curve):
        x = margin + (i / max(1, len(equity_curve) - 1)) * (width - 2 * margin)
        y = height - margin - ((val - mn) / span) * (height - 2 * margin)
        points.append(f"{x:.2f},{y:.2f}")

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">
<rect width="100%" height="100%" fill="white"/>
<text x="20" y="25" font-size="16">Equity Curve</text>
<polyline fill="none" stroke="#2563eb" stroke-width="2" points="{' '.join(points)}"/>
<line x1="{margin}" y1="{margin}" x2="{margin}" y2="{height-margin}" stroke="#444"/>
<line x1="{margin}" y1="{height-margin}" x2="{width-margin}" y2="{height-margin}" stroke="#444"/>
<text x="{margin}" y="{height-10}" font-size="12">{mn:.2f}</text>
<text x="{width-140}" y="{height-10}" font-size="12">{mx:.2f}</text>
</svg>'''
    EQUITY_SVG_PATH.write_text(svg)


if __name__ == "__main__":
    print("Étape 1) Création d'un dossier propre: crypto_backtest_clean (fait).")
    print("Étape 2) Vérification/installation des packages demandés.")
    check_and_install_packages()

    print("\nÉtape 3) Téléchargement des données BTCUSDT 5m (>= 1 an), extraction et conversion CSV.")
    candles = download_data(min_days=365)

    print("\nÉtape 4) Lancement du backtest avec la stratégie demandée.")
    res = run_backtest(candles)

    print("\nÉtape 5) Résultats:")
    print(f"Capital final   : {res.final_capital:.2f} USDT")
    print(f"Winrate         : {res.winrate:.2f}%")
    print(f"Max drawdown    : {res.max_drawdown:.2f}%")
    print(f"Profit factor   : {'inf' if math.isinf(res.profit_factor) else f'{res.profit_factor:.3f}'}")
    print(f"Nombre de trades: {res.total_trades}")
    print(f"Courbe equity (CSV): {EQUITY_CSV_PATH}")
    print(f"Courbe equity (SVG): {EQUITY_SVG_PATH}")
