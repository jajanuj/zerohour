import csv
from dataclasses import dataclass

from scalper.contracts import ContractLiquidityStats, export_ranking_csv, scan_volume_ranking


@dataclass
class FakeContract:
    code: str


class FakeKbars:
    def __init__(self, volumes):
        self.Volume = volumes


class FakeApi:
    def __init__(self, volume_by_code: dict):
        self.volume_by_code = volume_by_code

    def kbars(self, contract, start, end):
        volumes = self.volume_by_code.get(contract.code)
        if volumes is None:
            raise ValueError(f"no data for {contract.code}")
        return FakeKbars(volumes)


class TestScanVolumeRanking:
    def test_ranks_by_average_volume_descending(self):
        api = FakeApi({
            "MXFR1": [100, 200, 300],  # avg 200
            "TXFR1": [1000, 2000],     # avg 1500
        })
        contracts = [FakeContract("MXFR1"), FakeContract("TXFR1")]

        result = scan_volume_ranking(api, contracts)

        assert [r.symbol for r in result] == ["TXFR1", "MXFR1"]
        assert result[0].avg_daily_volume == 1500

    def test_skips_contract_on_error(self):
        api = FakeApi({"MXFR1": [100, 200]})
        contracts = [FakeContract("MXFR1"), FakeContract("BADCODE")]

        result = scan_volume_ranking(api, contracts)

        assert len(result) == 1
        assert result[0].symbol == "MXFR1"

    def test_skips_contract_with_no_volume_data(self):
        api = FakeApi({"MXFR1": []})
        contracts = [FakeContract("MXFR1")]

        result = scan_volume_ranking(api, contracts)

        assert result == []


class TestExportRankingCsv:
    def test_writes_csv_with_expected_columns(self, tmp_path):
        stats = [
            ContractLiquidityStats(symbol="MXFR1", avg_daily_volume=200.0),
            ContractLiquidityStats(symbol="TXFR1", avg_daily_volume=1500.0, sample_spread_ticks=1.2, sample_depth_qty=30.0),
        ]
        out_path = tmp_path / "ranking.csv"

        export_ranking_csv(stats, out_path)

        with out_path.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 2
        assert rows[0]["symbol"] == "MXFR1"
        assert rows[1]["sample_spread_ticks"] == "1.2"
