"""Small XLSX exports containing aggregates only; all text is an inline string, never a formula."""

from io import BytesIO
import re
from xml.etree.ElementTree import Element, SubElement, tostring
from zipfile import ZIP_DEFLATED, ZipFile
from .i18n import translate as t

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def sheet_xml(rows):
    root = Element("worksheet", xmlns=NS)
    data = SubElement(root, "sheetData")
    for index, values in enumerate(rows, 1):
        row = SubElement(data, "row", r=str(index))
        for column, value in enumerate(values, 1):
            number, label = column, ""
            while number:
                number, rem = divmod(number - 1, 26)
                label = chr(65 + rem) + label
            cell = SubElement(row, "c", r=f"{label}{index}")
            if isinstance(value, (float, int)):
                SubElement(cell, "v").text = str(value)
            else:
                cell.set("t", "inlineStr")
                text = SubElement(SubElement(cell, "is"), "t")
                text.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                text.text = re.sub(
                    r"[\x00-\x08\x0b\x0c\x0e-\x1f]",
                    "",
                    str(value if value is not None else "—"),
                )[:32767]
    return tostring(root, encoding="utf-8", xml_declaration=True)


def export_report(report):
    summary, comparison = report["summary"], report["comparison"]
    metrics = {
        "verified_visits": "Подтверждённые посещения",
        "included": "Учтённые оценки",
        "respondents": "Потребители с оценками",
        "new_respondents": "Новые авторы",
        "returning_respondents": "Вернувшиеся авторы",
        "repeat_respondents": "Повторные авторы за период",
        "satisfied_percent": "Доля довольных, %",
        "dissatisfied": "Недовольны, 1–4",
    }
    current_label = report["period"]["start"] + " — " + report["period"]["end"]
    prior_label = comparison["period"]["start"] + " — " + comparison["period"]["end"]
    overview = [
        [t("Показатель"), current_label, prior_label],
        *[
            [t(label), summary[key], comparison["summary"][key]]
            for key, label in metrics.items()
        ],
    ]
    organizations = [
        [t("Организация / сфера"), t("Сфера услуг"), *map(t, metrics.values())],
        *[
            [row["name"], row["category_label"], *[row[key] for key in metrics]]
            for row in report["organizations"]
        ],
    ]
    days = [
        [
            t("Дата"),
            t("Учтённые оценки"),
            t("Подтверждённые посещения"),
            t("Доля довольных, %"),
        ],
        *[
            [
                row["date"],
                row["included"],
                row["verified_visits"],
                row["satisfied_percent"],
            ]
            for row in report["trend"]
        ],
    ]
    methodology = [
        ["UTC", report["filters"]["source"]],
        *[[t(value)] for value in report["methodology"].values()],
    ]
    workbook = Element("workbook", xmlns=NS, attrib={"xmlns:r": REL})
    sheets = SubElement(workbook, "sheets")
    relationships = Element(
        "Relationships",
        xmlns="http://schemas.openxmlformats.org/package/2006/relationships",
    )
    types = Element(
        "Types", xmlns="http://schemas.openxmlformats.org/package/2006/content-types"
    )
    SubElement(
        types,
        "Default",
        Extension="rels",
        ContentType="application/vnd.openxmlformats-package.relationships+xml",
    )
    SubElement(types, "Default", Extension="xml", ContentType="application/xml")
    SubElement(
        types,
        "Override",
        PartName="/xl/workbook.xml",
        ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
    )
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for index, (name, rows) in enumerate(
            zip(
                ["Сводка", "Организации", "По дням", "Методика"],
                [overview, organizations, days, methodology],
            ),
            1,
        ):
            SubElement(
                sheets,
                "sheet",
                name=t(name),
                sheetId=str(index),
                attrib={"r:id": f"rId{index}"},
            )
            SubElement(
                relationships,
                "Relationship",
                Id=f"rId{index}",
                Type=REL + "/worksheet",
                Target=f"worksheets/sheet{index}.xml",
            )
            SubElement(
                types,
                "Override",
                PartName=f"/xl/worksheets/sheet{index}.xml",
                ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml",
            )
            archive.writestr(f"xl/worksheets/sheet{index}.xml", sheet_xml(rows))
        archive.writestr("xl/workbook.xml", tostring(workbook))
        archive.writestr("xl/_rels/workbook.xml.rels", tostring(relationships))
        archive.writestr("[Content_Types].xml", tostring(types))
        root_rels = Element(
            "Relationships",
            xmlns="http://schemas.openxmlformats.org/package/2006/relationships",
        )
        SubElement(
            root_rels,
            "Relationship",
            Id="rId1",
            Type=REL + "/officeDocument",
            Target="xl/workbook.xml",
        )
        archive.writestr("_rels/.rels", tostring(root_rels))
    return output.getvalue()
