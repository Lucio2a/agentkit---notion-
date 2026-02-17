# crypto_backtest_clean

Script simple pour débutant:

```bash
python3 backtest.py
```

Le script:
1. Vérifie/installe les packages demandés.
2. Télécharge BTCUSDT 5m depuis Binance Vision (au moins 1 an) et crée un CSV compatible Backtrader.
3. Lance le backtest de la stratégie demandée.
4. Affiche les métriques et exporte la courbe equity (`data/equity_curve.csv` + `data/equity_curve.svg`).

> Si le réseau bloque l'installation/téléchargement, le script continue avec un mode de démonstration local pour rester exécutable.
