"""The three numbers every table on the comparison page is made of."""


def summarise(rows):
    n = len(rows)
    hit1 = sum(r["rank"] == 1 for r in rows) / n
    hit5 = sum(bool(r["rank"]) and r["rank"] <= 5 for r in rows) / n
    mrr = sum(1 / r["rank"] for r in rows if r["rank"]) / n
    return dict(n=n, hit1=hit1, hit5=hit5, mrr=mrr)
