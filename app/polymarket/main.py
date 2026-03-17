from ..selection.runtime import load_runtime_selection, scan_and_select_runtime_market
from .client import PolymarketPublicClient
from .config import Config
from .maker import run_loop


def _maybe_apply_selected_token(config: Config) -> str | None:
    if config.selection_mode == "manual":
        return None
    selection = load_runtime_selection(config.selection_csv_path, venue="polymarket") if config.selection_mode == "csv" else scan_and_select_runtime_market("polymarket", output_path=config.selection_csv_path)
    if selection is None or not selection.market_id:
        raise ValueError(f"No Polymarket market selection available via mode={config.selection_mode}")
    config.token_id = selection.market_id
    return f"Selection mode {config.selection_mode} picked {selection.symbol} token_id={selection.market_id}"


def main() -> None:
    config = Config()
    selection_note = _maybe_apply_selected_token(config)
    config.validate()
    if selection_note:
        print(selection_note)
    client = PolymarketPublicClient(config.host)
    run_loop(config, client)


if __name__ == "__main__":
    main()
