"""`make seed`: personas -> marketplace seed + dev/hidden sets. Requires `make data` first."""

from scripts.data import gen_market, gen_portfolio


def main() -> None:
    gen_portfolio.main()
    gen_market.main()


if __name__ == "__main__":
    main()
