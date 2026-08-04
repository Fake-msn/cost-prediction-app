import { Divider, Grid, H1, H2, Stack, Stat, Table, Text } from 'qoder/canvas';

export default function DuckDBAuditReport() {
  return (
    <Stack gap={20}>
      <H1>DuckDB Duplicate Record Audit Report</H1>

      <Grid columns={4} gap={16}>
        <Stat value="PASS" label="project_meta" tone="success" />
        <Stat value="5,322" label="boq_item dups" />
        <Stat value="1" label="Affected Project" />
        <Stat value="232" label="Total Projects" />
      </Grid>

      <Divider />

      <H2>Checks Performed</H2>
      <Table
        headers={['Check', 'Method', 'Result']}
        rows={[
          ['project_meta by project_id', 'GROUP BY project_id HAVING COUNT > 1', '0 duplicates - PASS'],
          ['project_meta by (name, source_file)', 'GROUP BY name, source_file', '0 duplicates - PASS'],
          ['Old/new record coexistence', 'CASE buildings_json IS NULL vs NOT NULL per name', '0 mixed - PASS'],
          ['boq_items by (pid, boq_code)', 'GROUP BY project_id, boq_code', '5,322 duplicates in 65,027 - 1 project'],
          ['Data completeness', 'COUNT(*) vs COUNT(DISTINCT project_id)', '232 = 232 - PASS'],
        ]}
        rowTone={['success', 'success', 'success', 'warning', 'success']}
      />

      <Divider />

      <H2>Multi-Building Field Quality</H2>
      <Grid columns={4} gap={16}>
        <Stat value="25" label="buildings_json" tone="success" />
        <Stat value="14" label="mixed_types" />
        <Stat value="9" label="max_floor non-null" />
        <Stat value="0" label="old/new conflicts" tone="success" />
      </Grid>

      <Divider />

      <H2>Root Cause</H2>
      <Text>
        boq_items duplicates (project 7d47f60f6c, 南车安置小区) come from multiple Table-08 sheets
        in the same workbook sharing identical BOQ codes across different unit projects.
        INSERT OR REPLACE uses item_id PRIMARY KEY, and generate_item_id produces different
        hashes for each sheet extraction, creating unique item_ids for identical boq_codes.
      </Text>

      <Divider />

      <H2>Recommendation</H2>
      <Table
        headers={['Priority', 'Action', 'File']}
        rows={[
          ['P2', 'Include unit_project in generate_item_id hash for strict uniqueness', 'extract_boq.py:148'],
          ['None', 'project_meta is clean, no action needed', '-'],
          ['None', 'INSERT OR REPLACE correctly replaces old records, no coexistence risk', '-'],
        ]}
      />
    </Stack>
  );
}
