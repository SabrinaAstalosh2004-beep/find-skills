"""Прогнозирование потребления и проверка точности на истории.

Методы подбираются под тип спроса (классификация Syntetos–Boylan по ADI и CV²):
* регулярный (smooth) — SES / скользящее среднее;
* нерегулярный (intermittent/lumpy) — Croston, SBA, TSB;
* базовые методы для сравнения — наивный (последнее значение) и среднее за 3 мес.

Историческая проверка (backtest) — rolling origin: прогноз на месяц t строится только по данным до t−1.
"""
from __future__ import annotations

import math

import numpy as np


def classify(y: np.ndarray) -> str:
    nz = y[y > 0]
    if len(nz) == 0:
        return "Нет спроса"
    idx = np.flatnonzero(y > 0)
    adi = (idx[-1] - idx[0]) / max(1, len(idx) - 1) if len(idx) > 1 else len(y)
    cv2 = (nz.std() / nz.mean()) ** 2 if len(nz) > 1 and nz.mean() > 0 else 0.0
    if adi < 1.32:
        return "Регулярный (smooth)" if cv2 < 0.49 else "Неустойчивый (erratic)"
    return "Прерывистый (intermittent)" if cv2 < 0.49 else "Комковатый (lumpy)"


def one_step(y: np.ndarray, method: str, alpha: float = 0.15, beta: float = 0.1) -> np.ndarray:
    """f[t] — прогноз на период t, построенный по y[0..t-1]. f[0] = nan."""
    n = len(y)
    f = np.full(n, np.nan)
    if method == "naive":
        f[1:] = y[:-1]
    elif method == "ma3":
        for t in range(1, n):
            f[t] = y[max(0, t - 3):t].mean()
    elif method == "ses":
        lvl = y[0]
        for t in range(1, n):
            f[t] = lvl
            lvl = alpha * y[t] + (1 - alpha) * lvl
    elif method in ("croston", "sba"):
        z = p = None
        q = 1
        for t in range(n):
            if z is not None:
                fc = z / p
                f[t] = fc * (1 - alpha / 2) if method == "sba" else fc
            if y[t] > 0:
                if z is None:
                    z, p = y[t], q
                else:
                    z = alpha * y[t] + (1 - alpha) * z
                    p = alpha * q + (1 - alpha) * p
                q = 1
            else:
                q += 1
        f[np.isnan(f) & (np.arange(n) > 0)] = 0.0
    elif method == "tsb":
        z = None
        pr = 0.0
        for t in range(n):
            if z is not None:
                f[t] = pr * z
            occ = 1.0 if y[t] > 0 else 0.0
            if z is None:
                if occ:
                    z, pr = y[t], 1.0 / (t + 1)
            else:
                pr = beta * occ + (1 - beta) * pr
                if occ:
                    z = alpha * y[t] + (1 - alpha) * z
        f[np.isnan(f) & (np.arange(n) > 0)] = 0.0
    else:
        raise ValueError(method)
    return f


METHODS = {"naive": "Наивный (последнее значение)", "ma3": "Скользящее среднее 3 мес.", "ses": "Экспоненциальное сглаживание (SES)",
           "croston": "Croston", "sba": "SBA (Syntetos–Boylan)", "tsb": "TSB (Teunter–Syntetos–Babai)"}


def backtest(y: np.ndarray, start: int = 12, methods=None) -> dict[str, dict]:
    methods = methods or list(METHODS)
    out = {}
    act = y[start:]
    denom = act.sum()
    for m in methods:
        f = one_step(y, m)[start:]
        err = f - act
        out[m] = dict(label=METHODS[m], wape=float(np.abs(err).sum() / denom * 100) if denom > 0 else None,
                      bias=float(err.sum() / denom * 100) if denom > 0 else None, mae=float(np.abs(err).mean()),
                      rmse=float(np.sqrt((err ** 2).mean())))
    return out


def next_level(y: np.ndarray, method: str) -> float:
    """Прогноз уровня спроса на следующий период по всем доступным данным."""
    ext = np.append(y, 0.0)
    v = one_step(ext, method)[-1]
    return float(0.0 if np.isnan(v) else v)


def residual_sigma(y: np.ndarray, method: str, start: int = 6) -> float:
    f = one_step(y, method)
    e = (y - f)[start:]
    e = e[~np.isnan(e)]
    return float(e.std()) if len(e) > 1 else 0.0


def recommended_method(cls: str) -> str:
    """SES — для регулярного спроса; TSB — для прерывистого/комковатого: в отличие от Croston/SBA
    снижает прогноз при прекращении спроса (устаревание), что подтверждено исторической проверкой (витрина 12/13)."""
    return "ses" if cls.startswith("Регулярный") or cls.startswith("Неустойчивый") else "tsb"


def poisson_quantile(lam: float, p: float) -> int:
    """Минимальное k, при котором P(X ≤ k) ≥ p для X ~ Poisson(lam)."""
    if lam <= 0:
        return 0
    k = 0
    term = math.exp(-lam)
    cdf = term
    while cdf < p and k < 1000:
        k += 1
        term *= lam / k
        cdf += term
    return k
