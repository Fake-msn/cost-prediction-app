import { Divider, Grid, H1, H2, Stack, Stat, Table, Text } from 'qoder/canvas';

export default function DuckDBReconstructionReport() {
  return (
    <Stack gap={20}>
      <H1>DuckDB Database Reconstruction Report</H1>

      <Grid columns={4} gap={16}>
        <Stat value="152" label="project_meta" tone="success" />
        <Stat value="65,027" label="boq_items" tone="success" />
        <Stat value="71" label="cost_breakdown" tone="success" />
        <Stat value="32.5 MB" label="File Size" />
      </Grid>

      <Divider />

      <H2>Pipeline Steps</H2>
      <Table
        headers={['Step', 'Script', 'Result']}
        rows={[
          ['0. Backup', 'Copy-Item', 'Backup saved to data/'],
          ['1. Init', 'init_duckdb.py', '4 tables + 7 price_index rows'],
          ['2. Migrate ×2', 'migrate_to_duckdb.py', '46 real + 80 sample = 126 projects'],
          ['3. BOQ Extract ×50+', 'extract_boq.py', '65,027 boq_items across 50+ source folders'],
          ['4. Cost Breakdown', 'cost_breakdown_extractor.py', '71 projects with labor cost data'],
          ['5. Verify', 'SQL COUNT(*)+', 'All target rows exceeded'],
        ]}
      />

      <Divider />

      <H2>Bugs Fixed</H2>
      <Table
        headers={['File', 'Issue', 'Fix']}
        rows={[
          ['cost_breakdown_extractor.py:605', 'SQL INSERT 26 placeholders vs 25 values', 'Removed extra ? from VALUES clause'],
          ['cost_breakdown_extractor.py:757', 'UnicodeEncodeError from emoji in GBK terminal', 'Replaced emoji with ASCII [OK]/[FAIL]'],
          ['cost_breakdown_extractor.py:108', 'find_source_excel threshold too strict', 'Added long_match fallback for single-keyword projects'],
        ]}
        rowTone={['warning', 'warning', 'warning']}
      />

      <Divider />

      <H2>Data Quality</H2>
      <Grid columns={3} gap={16}>
        <Stat value="26" label="Projects with BOQ detail" />
        <Stat value="71" label="Projects with labor cost" />
        <Stat value="7" label="Price index years" />
      </Grid>

      <Text tone="secondary" size="small">
        Source: D:\工程造价预测AI项目模板 (50+ folders) + data/sample_training_data.xlsx + data/real_training_data.xlsx
      </Text>
      <Text tone="secondary" size="small">
        81/152 projects without cost breakdown are synthetic training data (sample_training_data.xlsx) with no corresponding source files.
      </Text>
    </Stack>
  );
}
