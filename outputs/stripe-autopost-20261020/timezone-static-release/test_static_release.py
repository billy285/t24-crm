import copy,importlib.util
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('timezone_static_test',ROOT/'static_release.py');r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)

def snapshot():
 rows={f'table_{i}':{'count':1,'columns':['id'],'schema':{},'indexes':{},'rows_sha256':'a'*64} for i in range(113)}
 rows['stripe_history_scan_states']={'count':18,'columns':['binding_id'],'schema':{},'indexes':{},'rows_sha256':'a'*64}
 return rows

def test_only_normal_scan_checkpoint_values_may_change():
 before=snapshot();after=copy.deepcopy(before);after['stripe_history_scan_states']['rows_sha256']='b'*64
 assert r.compare_rows(before,after) is True

@pytest.mark.parametrize('mutation',[
 lambda rows:rows['table_0'].update(rows_sha256='b'*64),
 lambda rows:rows['table_0'].update(count=2),
 lambda rows:rows['stripe_history_scan_states'].update(count=19),
 lambda rows:rows['stripe_history_scan_states'].update(schema={'unauthorized':True}),
 lambda rows:rows.update(extra={}),
])
def test_all_other_rows_and_every_schema_stay_exact(mutation):
 before=snapshot();after=copy.deepcopy(before);mutation(after)
 with pytest.raises(RuntimeError):r.compare_rows(before,after)

def test_static_publisher_has_no_backend_or_database_mutation_calls():
 source=(ROOT/'static_release.py').read_text()
 for text in ("['docker','stop'","['docker','start'","['docker','rename'",".migrate(",'.backup(','.run_batch(','.queue_pending(','UPDATE ','INSERT ','DELETE ','ALTER TABLE','CREATE TABLE'):
  assert text not in source
 assert 'self.rollback_root(r)' in source and 'm.replace_nginx(original,changed)' in source
