"""Behavioral checks for the named clinical metric input contract; no model calls."""
import json
from pathlib import Path
import tempfile
import unittest

from cart_db.agent_output import OutputError, prepare_output


class ClinicalMetricContractTests(unittest.TestCase):
    def normalize(self, **fields):
        rows = [
            {"table": "car", "data": {"car_id": "clinical-car", "modules": []}},
            {"table": "evidence", "data": {
                "record_id": "result", "source_type": "literature", "source_id": "test-source",
                "study_type": "clinical", "car.car_id": "clinical-car", **fields,
            }},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.jsonl"
            path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            output = prepare_output(path)
        return json.loads(output.splitlines()[1])["data"]

    def test_individual_response_is_categorical_not_a_calculated_rate(self):
        data = self.normalize(**{"clinical.response": "CRi", "clinical.mrd_status": "negative"})
        self.assertEqual(data["clinical.response"], "CRi")
        self.assertEqual(data["clinical.mrd_status"], "negative")
        self.assertIsNone(data["clinical.cri_rate"])

    def test_count_only_report_keeps_rate_unknown(self):
        data = self.normalize(**{"clinical.mrd_negative_cr_rate": {"numerator": 23, "denominator": 25}})
        rate = data["clinical.mrd_negative_cr_rate"]
        self.assertEqual((rate["numerator"], rate["denominator"]), (23, 25))
        self.assertIsNone(rate["rate"])

    def test_zero_grade_is_not_converted_to_zero_incidence(self):
        data = self.normalize(**{"clinical.icans": {"grade": "0"}})
        self.assertEqual(data["clinical.icans"]["grade"], "0")
        self.assertIsNone(data["clinical.icans"]["rate"])

    def test_survival_not_reached_is_not_zero_duration(self):
        data = self.normalize(**{"clinical.os": {"status": "not_reached"}})
        self.assertEqual(data["clinical.os"]["status"], "not_reached")
        self.assertIsNone(data["clinical.os"]["duration"])

    def test_wrong_rate_and_count_types_are_rejected(self):
        for value in (92, {"numerator": 23.5}, {"denominator": "25"}):
            with self.subTest(value=value), self.assertRaises(OutputError):
                self.normalize(**{"clinical.cr_rate": value})

    def test_peak_requires_measurement_not_numeric_text(self):
        with self.assertRaises(OutputError):
            self.normalize(**{"clinical.cmax": "190000"})

    def test_figure_estimate_keeps_its_distinct_kind(self):
        estimate = {"kind": "image_estimated_range", "lower": 370000, "upper": 390000,
                    "unit": "copies/ug DNA", "raw": "Pixel estimate; Fig. 3C; source range 370000–390000"}
        data = self.normalize(**{"clinical.cmax": estimate})
        self.assertEqual(data["clinical.cmax"]["kind"], "image_estimated_range")
        self.assertEqual(data["clinical.cmax"]["lower"], 370000)
        self.assertIsNone(data["clinical.cmax"]["value"])
        with self.assertRaises(OutputError):
            self.normalize(**{"clinical.cmax": {**estimate, "upper": 370000}})

    def test_retired_broad_result_buckets_are_rejected(self):
        for name in ("clinical.cohorts", "clinical.efficacy_outcomes", "clinical.safety_outcomes", "clinical.cell_kinetics"):
            with self.subTest(name=name), self.assertRaises(OutputError):
                self.normalize(**{name: []})


if __name__ == "__main__":
    unittest.main()
