"""A branded, editable Excel dashboard backed by the app's reporting data."""
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from openpyxl.chart import BarChart, ScatterChart, Series, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.chart.legend import LegendEntry
from openpyxl.chart.marker import DataPoint
from openpyxl.drawing.image import Image
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

NAVY = '244C78'
ORANGE = 'F36B21'
TEAL = '0099CB'
MUTED = '7183A0'
BACKGROUND = 'F4F7FB'
YEAR_COLORS = ['244C78', '0099CB', 'F36B21', '268575', 'B03178', 'A48D53']
COMPANY_COLORS = ['244C78', '3788AA', '55AAA8', '97C8B9', 'D2E4DB', '8293AD']
EUROS = '"€" #,##0.00'


def safe_text(value):
    text = str(value)
    return "'" + text if text.lstrip().startswith(('=', '+', '-', '@')) else text


def year_color(year):
    return YEAR_COLORS[(int(year) - 2024) % len(YEAR_COLORS)]


def block(sheet, cell_range, value, size=11, color=NAVY, bold=False,
          fill=None, align='left'):
    if fill:
        for row in sheet[cell_range]:
            for cell in row:
                cell.fill = PatternFill('solid', fgColor=fill)
    sheet.merge_cells(cell_range)
    cell = sheet[cell_range.split(':')[0]]
    cell.value = safe_text(value) if isinstance(value, str) else value
    cell.font = Font(name='Aptos', size=size, color=color, bold=bold)
    cell.alignment = Alignment(horizontal=align, vertical='center', wrap_text=True)
    return cell


def table_header(sheet, row, values):
    for index, value in enumerate(values, 1):
        cell = sheet.cell(row, index, safe_text(value))
        cell.font = Font(name='Aptos', color='FFFFFF', bold=True)
        cell.fill = PatternFill('solid', fgColor=NAVY)
        cell.alignment = Alignment(vertical='center', wrap_text=True)
    sheet.row_dimensions[row].height = 30


def style_chart(chart, title, width=14.5, height=10):
    chart.title = title
    chart.width = width
    chart.height = height
    chart.style = 10
    chart.legend.position = 'b'
    # Chart source data is on a hidden sheet; it must remain visible in charts.
    chart.visible_cells_only = False
    chart.display_blanks = 'gap'
    chart.y_axis.numFmt = EUROS
    chart.y_axis.scaling.min = 0
    chart.x_axis.title = None
    chart.y_axis.title = 'Bedrag (€)'


def period_chart(source, first_column, years, categories, title):
    chart = BarChart()
    chart.type = 'col'
    chart.grouping = 'clustered'
    chart.overlap = 0
    chart.gapWidth = 500 if len(categories) == 1 else 70
    style_chart(chart, title)
    # Avoid calling Reference with min_row > max_row in an empty/no-company app.
    last_row = len(categories) + 1
    for index, year in enumerate(years):
        column = first_column + index
        chart.add_data(Reference(source, min_col=column, min_row=1, max_row=last_row), titles_from_data=True)
        series = chart.series[-1]
        series.graphicalProperties.solidFill = year_color(year)
        series.graphicalProperties.line.noFill = True
    chart.set_categories(Reference(source, min_col=1, min_row=2, max_row=last_row))
    chart.dLbls = DataLabelList()
    chart.dLbls.showVal = True
    chart.dLbls.showLegendKey = chart.dLbls.showCatName = chart.dLbls.showSerName = False
    chart.dLbls.showPercent = chart.dLbls.showBubbleSize = False
    chart.dLbls.numFmt = EUROS
    chart.dLbls.dLblPos = 'outEnd'

    # 2026 is one informational annual column. Only quarters of each individual
    # measurement year share a line, and missing quarters never become zeros.
    quarterly_years = [year for year in years if year != '2026']
    if quarterly_years:
        line = ScatterChart()
        style_chart(line, title)
        line.scatterStyle = 'lineMarker'
        line.x_axis.axId = 201
        line.x_axis.crossAx = 202
        line.y_axis.axId = 202
        line.y_axis.crossAx = 201
        line.x_axis.delete = line.y_axis.delete = True
        line.y_axis.title = None
        line.x_axis.majorGridlines = line.y_axis.majorGridlines = None
        line.x_axis.scaling.min = .5
        line.x_axis.scaling.max = len(categories) + .5
        # The line and columns must use exactly the same euroscale.
        maximum = max(Decimal(str(source.cell(row, first_column + i).value or 0))
                      for row in range(2, last_row + 1) for i in range(len(years)))
        chart.y_axis.scaling.max = float(maximum * Decimal('1.15')) if maximum else 1
        line.y_axis.scaling.max = chart.y_axis.scaling.max
        for year in quarterly_years:
            column = first_column + years.index(year)
            # Scatter X coordinates align each line with its own year's column
            # centre, rather than the shared category centre of a LineChart.
            x_column = 2 * len(years) + 6 + years.index(year)
            series = Series(Reference(source, min_col=column, min_row=2, max_row=last_row),
                            Reference(source, min_col=x_column, min_row=2, max_row=last_row), title=year)
            series.graphicalProperties.line.solidFill = year_color(year)
            series.graphicalProperties.line.width = 25000
            series.marker.symbol = 'circle'
            series.marker.size = 5
            series.marker.graphicalProperties.solidFill = year_color(year)
            series.marker.graphicalProperties.line.solidFill = 'FFFFFF'
            line.series.append(series)
        chart.legend.legendEntry = [LegendEntry(idx=len(years) + index, delete=True)
                                    for index in range(len(quarterly_years))]
        chart += line
    return chart


def add_dashboard(workbook, state, rows, report, filtered=False):
    """Add a first Dashboard sheet without changing the existing import tables."""
    dashboard = workbook.create_sheet('Dashboard', 0)
    workbook.active = 0
    dashboard.sheet_view.showGridLines = False
    dashboard.sheet_properties.pageSetUpPr.fitToPage = True
    dashboard.sheet_properties.tabColor = ORANGE
    dashboard.page_setup.orientation = 'landscape'
    dashboard.page_setup.paperSize = dashboard.PAPERSIZE_A3
    dashboard.page_setup.fitToWidth = 1
    dashboard.page_setup.fitToHeight = 0
    dashboard.print_options.horizontalCentered = True
    dashboard.print_area = 'A1:AM74'
    dashboard.freeze_panes = 'A10'
    for column in range(1, 40):
        dashboard.column_dimensions[get_column_letter(column)].width = 4.3
    for row in range(1, 75):
        dashboard.row_dimensions[row].height = 18
        for column in range(1, 40):
            cell = dashboard.cell(row, column)
            cell.fill = PatternFill('solid', fgColor=BACKGROUND)
    logo = Image(str(Path(__file__).parent / 'assets' / 'tve-group-logo.png'))
    logo.width = 225
    logo.height = 225 * 745 / 2112
    dashboard.add_image(logo, 'B2')
    block(dashboard, 'L2:AM3', 'Dashboard · TVE GROUP', 22, bold=True)
    exported_at = datetime.now(ZoneInfo('Europe/Amsterdam')).strftime('%d-%m-%Y %H:%M')
    block(dashboard, 'L4:AM5', 'Leveranciersbeheer · geëxporteerd op ' + exported_at, 10, MUTED)
    selected = next((company['name'] for company in state['companies']
                     if company['id'] == report['selected_company']), 'Geen bedrijf')
    heading = 'Jaargegevens 2026 · informatief' if report['informative_only'] else 'Prijsinvoer ' + report['period']
    block(dashboard, 'B7:AM8', heading + ' · bedrijfsoverzicht: ' + selected, 14, bold=True)
    coverage = report['coverage']
    summary = f"{coverage['expected'] - coverage['missing']} van {coverage['expected']} bedrijfsprijzen ingevuld."
    if report['deadline']:
        summary += ' Uiterlijk ' + datetime.fromisoformat(report['deadline']).strftime('%d-%m-%Y') + '.'
    block(dashboard, 'B9:AM10', summary, 10, MUTED)
    metrics = [(len({row['supplier_id'] for row in rows}), 'Unieke leveranciers'),
               (len(rows), 'Leveranciersregels'),
               (len({row['category_id'] for row in rows}), 'Categorieën in gebruik'),
               (len({company_id for row in rows for company_id in row['company_ids']})
                if filtered else len(state['companies']), 'Bedrijven')]
    for (start, end), (value, label) in zip([(2, 10), (12, 20), (22, 30), (32, 39)], metrics):
        left, right = get_column_letter(start), get_column_letter(end)
        block(dashboard, f'{left}12:{right}13', label, 10, bold=True, fill='FFFFFF')
        block(dashboard, f'{left}14:{right}16', value, 28, color=ORANGE, bold=True, fill='FFFFFF')

    # A readable period table is included, while the clustered-series matrix
    # used by native charts lives on a hidden technical worksheet.
    periods = workbook.create_sheet('Periodebedragen')
    table_header(periods, 1, ['Periode', 'Bedrijf: ' + selected, 'Gehele groep', 'Status', 'Invoer'])
    periods.freeze_panes = 'B2'
    for index, point in enumerate(report['series'], 2):
        periods.append([safe_text(point['key']), Decimal(point['total']) if point['total'] is not None else None,
                        Decimal(point['group_total']) if point['group_total'] is not None else None,
                        'Nog niet begonnen' if point['future'] else 'Lopend' if point['current'] else 'Afgerond',
                        'Heel jaar · informatief' if point['granularity'] == 'year' else 'Kwartaal'])
        periods.cell(index, 2).number_format = EUROS
        periods.cell(index, 3).number_format = EUROS
    for column, width in zip('ABCDE', [18, 28, 28, 24, 28]):
        periods.column_dimensions[column].width = width
    periods.auto_filter.ref = periods.dimensions

    source = workbook.create_sheet('Grafiekgegevens')
    source.sheet_state = 'hidden'
    years = sorted({point['key'][:4] for point in report['series']})
    annual = [point['key'] for point in report['series'] if point['granularity'] == 'year']
    categories = annual + (['Q1', 'Q2', 'Q3', 'Q4'] if any(point['granularity'] == 'quarter' for point in report['series']) else [])
    source.append(['Periode'] + years + years)
    for category in categories:
        cells = [category]
        for field in ['total', 'group_total']:
            for year in years:
                key = category if category == year else f'{year}-{category}'
                point = next((point for point in report['series'] if point['key'] == key), None)
                cells.append(Decimal(point[field]) if point and point[field] is not None else None)
        source.append(cells)
        for column in range(2, 2 + 2 * len(years)):
            source.cell(source.max_row, column).number_format = EUROS
    # A category spans one unit. With zero overlap and gapWidth=70, each column
    # is 1/(number of years + .7) units wide inside its category cluster.
    for index, year in enumerate(years):
        x_column = 2 * len(years) + 6 + index
        source.cell(1, x_column, 'Kolompositie ' + year)
        offset = (index - (len(years) - 1) / 2) / (len(years) + .7)
        for category_index, category in enumerate(categories, 1):
            source.cell(category_index + 1, x_column, category_index + offset)
    dashboard.add_chart(period_chart(source, 2, years, categories, 'Bedrijfsoverzicht · ' + selected), 'B19')
    dashboard.add_chart(period_chart(source, 2 + len(years), years, categories, 'Groepsoverzicht'), 'V19')
    note = ('2026 toont één jaarbedrag. Kwartaalmetingen beginnen op 1 januari 2027. '
            'Het jaarbedrag wordt niet met een kwartaal vergeleken. Elke grafiek heeft een eigen euroschaal. '
            'Ontbrekende bedragen blijven leeg.')
    block(dashboard, 'B42:AM44', note, 10, MUTED)

    count_column = 2 * len(years) + 3
    source.cell(1, count_column, 'Bedrijf')
    source.cell(1, count_column + 1, 'Unieke leveranciers')
    for index, company in enumerate(state['companies'], 2):
        source.cell(index, count_column, safe_text(company['name']))
        source.cell(index, count_column + 1,
                    len({row['supplier_id'] for row in rows if company['id'] in row['company_ids']}))
    if state['companies']:
        company_chart = BarChart()
        style_chart(company_chart, 'Leveranciers per bedrijf · aantal unieke leveranciers', 29.8, 10)
        company_chart.type = 'col'
        company_chart.legend = None
        company_chart.y_axis.title = 'Unieke leveranciers'
        company_chart.y_axis.numFmt = '0'
        company_chart.y_axis.majorUnit = 1
        company_chart.add_data(Reference(source, min_col=count_column + 1, min_row=1,
                                         max_row=len(state['companies']) + 1), titles_from_data=True)
        company_chart.set_categories(Reference(source, min_col=count_column, min_row=2,
                                               max_row=len(state['companies']) + 1))
        for index, company in enumerate(state['companies']):
            point = DataPoint(idx=index)
            point.graphicalProperties.solidFill = COMPANY_COLORS[index % len(COMPANY_COLORS)]
            point.graphicalProperties.line.noFill = True
            company_chart.series[0].data_points.append(point)
        company_chart.dLbls = DataLabelList()
        company_chart.dLbls.showVal = True
        company_chart.dLbls.showLegendKey = company_chart.dLbls.showCatName = company_chart.dLbls.showSerName = False
        company_chart.dLbls.showPercent = company_chart.dLbls.showBubbleSize = False
        company_chart.dLbls.numFmt = '0'
        company_chart.dLbls.dLblPos = 'outEnd'
        dashboard.add_chart(company_chart, 'B47')
    filter_note = ('Actieve selectie: kerncijfers, leveranciersgrafiek en gegevensbladen volgen het filter. '
                   'De periodegrafieken tonen het gekozen bedrijf en de volledige groep.') if filtered else 'Alle leveranciersgegevens zijn meegenomen.'
    block(dashboard, 'B70:AM72', filter_note, 10, MUTED)
    block(dashboard, 'B73:AM74', 'Onderliggende gegevens staan op de overige tabbladen. De grafieken in Excel blijven bewerkbaar.', 10, MUTED)
    return dashboard
