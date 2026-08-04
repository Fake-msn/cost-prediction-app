import { Divider, Grid, H1, H2, Stack, Stat, Table, Text } from 'qoder/canvas';

export default function MultiBuildingReport() {
  return (
    <Stack gap={20}>
      <H1>Multi-Building Full-Chain Integration Report</H1>

      <Grid columns={4} gap={16}>
        <Stat value="4/4" label="Requirements Met" tone="success" />
        <Stat value="7/8" label="Models Retrained" />
        <Stat value="25" label="Projects with buildings_json" tone="success" />
        <Stat value="14" label="Mixed Type Projects" />
      </Grid>

      <Divider />

      <H2>Pipeline Steps</H2>
      <Table
        headers={['Step', 'Action', 'Result']}
        rows={[
          ['1. Data Extraction', 'extract_boq.py on 46 folders + migrate_to_duckdb.py x2', '232 projects, 65,027 boq_items'],
          ['2. Schema Update', 'init_duckdb.py ALTER TABLE 5 columns', 'building_count, buildings_json, max_floor, min_floor, mixed_types'],
          ['3. Model Retrain', 'POST /api/train', '7/8 trained, 126 samples, 64,155 BOQ'],
          ['4. Full-Chain Verify', 'API + frontend + prediction test', 'buildings array accepted, area validation active'],
        ]}
      />

      <Divider />

      <H2>Verification Evidence</H2>
      <Grid columns={3} gap={16}>
        <Stat value="232" label="project_meta rows" />
        <Stat value="65,027" label="boq_items rows" />
        <Stat value="32.5 MB" label="DuckDB Size" />
      </Grid>

      <Table
        headers={['Test', 'Payload', 'Result']}
        rows={[
          ['Single Building (backward compat)', 'floors=10, no buildings[]', 'scale_factor=1.0, standard prediction'],
          ['Multi Building (2 towers)', '20F residential + 3F commercial', 'fused_total_cost=36,100,412, scale_factor=1.4'],
          ['Area Validation', 'sum(area) != total_area', 'Toast error, submission blocked'],
          ['API Schema', 'buildings: [{floors,type,area}]', '200 OK, valid BuildingItem[]'],
        ]}
        rowTone={['success', 'success', 'warning', 'success']}
      />

      <Divider />

      <H2>Bugs Fixed</H2>
      <Table
        headers={['File', 'Issue', 'Fix']}
        rows={[
          ['cost_breakdown_extractor.py', 'SQL 26 ? vs 25 values', 'Removed extra placeholder'],
          ['cost_breakdown_extractor.py', 'UnicodeEncodeError in GBK', 'ASCII [OK]/[FAIL]'],
          ['document_parser.py', 'Tesseract hardcoded C:\\ path', 'platform.system() == "Windows" guard'],
          ['app.js', 'No area sum validation', 'validateStep1() checks sum vs total_area'],
        ]}
        rowTone={['warning', 'warning', 'warning', 'warning']}
      />

      <Divider />

      <H2>Changed Files</H2>
      <Text tone="secondary" size="small">
        backend/ml_models.py, backend/main.py, backend/agent.py,
        backend/scripts/init_duckdb.py, backend/scripts/extract_boq.py, backend/scripts/migrate_to_duckdb.py,
        backend/cost_breakdown_extractor.py, backend/document_parser.py,
        frontend/static/js/app.js, frontend/app.html,
        .env.example, start.bat, start.sh
      </Text>

      <Divider />

      <H2>Remaining Issues</H2>
      <Table
        headers={['Issue', 'Impact', 'Status']}
        rows={[
          ['Floor detection accuracy', 'parse_buildings_from_unit_names regex matches poorly on Table-08 sheet names', 'Known limitation'],
          ['basement field not in UI', 'BuildingItem.basement defined but no frontend input', 'Minor gap'],
          ['Idle features', 'residential_ratio, commercial_ratio, avg_floor extracted but not in training', 'Future work'],
          ['Excel training data', 'migrate_to_duckdb.py only maps building_count for Excel, not buildings_json', 'Data source limitation'],
        ]}
        rowTone={['warning', undefined, undefined, undefined]}
      />
    </Stack>
  );
}
