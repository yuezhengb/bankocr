from bankocr.benchmark.resources import peak_rss_mb


def test_peak_rss_reports_a_positive_process_measurement() -> None:
    assert peak_rss_mb() > 0
