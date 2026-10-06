#!/usr/bin/env python3
"""Regenerate synthetic fixtures with `pip install mmdb-writer==0.2.7`."""
from pathlib import Path
from mmdb_writer import MMDBWriter
from netaddr import IPSet

root = Path(__file__).parent / 'fixtures'
root.mkdir(exist_ok=True)
for name, populated in [('empty', False), ('populated', True)]:
    writer = MMDBWriter(ip_version=6, database_type='GeoIP2-Reload-Test',
                        description='Synthetic integration fixture')
    if populated:
        for network in ('::/1', '8000::/1'):
            writer.insert_network(IPSet([network]), {'value': 'updated'})
    writer.to_db_file(str(root / (name + '.mmdb')))
