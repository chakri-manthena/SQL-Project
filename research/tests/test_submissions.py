import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from submissions import csv_quote_diagnostics, parse_2019_export, parse_2020_exports  # noqa: E402


class SubmissionParserTests(unittest.TestCase):
    def test_2019_reader_uses_csv_quoting_and_destination_mapping(self):
        raw = (
            "id,destinationTable,participant,sourceTable,statement,submitTime\n"
            '670,charlied,306,charlie,"SELECT * FROM charlie WHERE TFR < 1850 & CFR < 1650",'
            '"2019-07-11 15:51:13.728000"\n'
        )

        [record] = parse_2019_export(raw, "216_su19_queries.csv")

        self.assertEqual(record["problem"], 3)
        self.assertEqual(record["statement"], "SELECT * FROM charlie WHERE TFR < 1850 & CFR < 1650")
        self.assertIsNone(record["correct_flag"])

    def test_csv_quote_diagnostic_counts_malformed_field_widths(self):
        raw = (
            "id,destinationTable,participant,sourceTable,statement,submitTime,canBeDisplayed,correct,count,problem\n"
            '1,NULL,p,alpha,"SELECT x IN ("a", "b")",2020-01-01,0,0,0,"Problem 1"\n'
        )

        diagnostic = csv_quote_diagnostics(raw)

        self.assertEqual(diagnostic["physical_records"], 1)
        self.assertEqual(diagnostic["records_with_11_or_12_fields"], 1)

    def test_preserves_inner_quotes_and_commas(self):
        raw = (
            "id,destinationTable,participant,sourceTable,statement,submitTime,canBeDisplayed,correct,count,problem\n"
            '2446,NULL,student,bravo,"SELECT DISTINCT CUI1, RUI FROM bravo WHERE REL IN ("RO", "AY")",'
            "2020-10-01,true,false,2,Problem 2\n"
        )

        [record] = parse_2020_exports(raw, "216_f20_queries.csv")

        self.assertEqual(record["id"], 2446)
        self.assertEqual(record["statement"], 'SELECT DISTINCT CUI1, RUI FROM bravo WHERE REL IN ("RO", "AY")')
        self.assertTrue(record["had_inner_quotes"])
        self.assertFalse(record["correct_flag"])
        self.assertEqual(record["problem"], 2)

    def test_null_statement_is_kept_as_null(self):
        raw = "1,NULL,student,alpha,NULL,2020-10-02,false,false,0,Problem 1\n"

        [record] = parse_2020_exports(raw, "326_f20_queries.csv")

        self.assertIsNone(record["statement"])
        self.assertFalse(record["had_inner_quotes"])

    def test_unquoted_non_null_statement_is_preserved(self):
        raw = "2,NULL,student,alpha,sql,2020-10-03,true,false,1,Problem 1\n"

        [record] = parse_2020_exports(raw, "216_f20_queries.csv")

        self.assertEqual(record["statement"], "sql")

    def test_invalid_problem_label_fails_closed(self):
        raw = "3,NULL,student,alpha,SELECT 1,2020-10-03,true,false,1,Problem X\n"

        with self.assertRaisesRegex(ValueError, "Invalid problem label"):
            parse_2020_exports(raw, "216_f20_queries.csv")


if __name__ == "__main__":
    unittest.main()