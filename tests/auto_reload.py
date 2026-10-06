#!/usr/bin/env python3
"""Integration regression for HTTP/stream auto_reload (Python standard library only)."""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request


def free_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nginx', required=True)
    parser.add_argument('--module-dir', type=Path, required=True)
    args = parser.parse_args()
    fixtures = Path(__file__).parent / 'fixtures'
    with tempfile.TemporaryDirectory(prefix='geoip2-reload-') as temporary:
        prefix = Path(temporary)
        prefix.chmod(0o755)
        database = prefix / 'test.mmdb'
        shutil.copyfile(fixtures / 'populated.mmdb', database)
        database.chmod(0o644)
        zero_database = prefix / "zero.mmdb"
        shutil.copyfile(database, zero_database)
        zero_database.chmod(0o644)
        http_port, stream_port = free_port(), free_port()
        modules = args.module_dir.resolve()
        config = prefix / 'nginx.conf'
        config.write_text(f'''load_module {modules}/ngx_http_geoip2_module.so;
load_module {modules}/ngx_stream_geoip2_module.so;
worker_processes 2;
timer_resolution 100ms;
pid {prefix}/nginx.pid;
error_log {prefix}/error.log info;
events {{ worker_connections 128; }}
http {{
    access_log off;
    set_real_ip_from 127.0.0.1;
    real_ip_header X-Test-IP;
    geoip2 {database} {{
        auto_reload 1s;
        $result value;
    }}
    geoip2 {zero_database} {{ $explicit_result source=$arg_ip value; }}
    server {{
        listen 127.0.0.1:{http_port} reuseport;
        location / {{ return 200 "$pid|$remote_addr|$result|$explicit_result|$guard"; }}
        # Evaluate GeoIP during server rewrite, before the content handler.
        set $guard empty;
        if ($result = updated) {{ set $guard updated; }}
    }}
}}
stream {{
    geoip2 {database} {{ auto_reload 1s; $result value; }}
    server {{ listen 127.0.0.1:{stream_port} reuseport; return "$pid|$result"; }}
}}
''')
        nginx = [str(Path(args.nginx).resolve()), '-p', str(prefix) + '/', '-c', str(config)]
        check = subprocess.run(nginx + ['-t'], text=True, capture_output=True)
        assert check.returncode == 0, check.stdout + check.stderr
        process = subprocess.Popen(nginx + ['-g', 'daemon off;'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def http(ip='198.51.100.10', explicit=''):
            req = urllib.request.Request(f'http://127.0.0.1:{http_port}/?ip={explicit}', headers={'X-Test-IP': ip})
            with opener.open(req, timeout=3) as response:
                worker, address, result, explicit_result, guard = response.read().decode().split('|')
            assert address == ip, ('RealIP handler must still run', address, ip)
            return worker, result, explicit_result, guard
        def stream():
            with socket.create_connection(('127.0.0.1', stream_port), timeout=3) as client:
                data = b''
                while True:
                    part = client.recv(4096)
                    if not part:
                        break
                    data += part
            return data.decode().split('|')
        def replace(source):
            candidate = prefix / 'candidate.mmdb'
            candidate.write_bytes(source)
            candidate.chmod(0o644)
            stamp = max(time.time(), int(database.stat().st_mtime) + 1)
            os.utime(candidate, (stamp, stamp))
            os.replace(candidate, database)
            # Let each worker's check interval elapse before the next request.
            time.sleep(2.1)
        try:
            deadline = time.monotonic() + 5
            while True:
                try:
                    http()
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise
                    time.sleep(.05)
            for ip in ('::', '0.0.0.0'):
                assert http(explicit=ip)[2] == 'updated', ('all-zero lookup', ip)
            http_workers, stream_workers = set(), set()
            for fixture, expected in [('empty.mmdb', ''), ('populated.mmdb', 'updated'), ('empty.mmdb', ''), ('populated.mmdb', 'updated')]:
                # Populate the same-IP HTTP cache in both workers before swapping.
                for _ in range(100):
                    http()
                replace((fixtures / fixture).read_bytes())
                first_stream_request = set()
                for _ in range(100):
                    for ip in ('198.51.100.10', '2001:db8::10'):
                        worker, result, _, guard = http(ip)
                        assert result == expected, ('first request after interval', fixture, worker, result, (prefix / 'error.log').read_text())
                        assert guard == (expected or 'empty'), ('server rewrite', fixture, guard)
                        http_workers.add(worker)
                    worker, result = stream()
                    # Stream checks in LOG: the first session triggers the reload.
                    if worker in first_stream_request:
                        assert result == expected, ('stream cache', fixture, worker, result)
                    first_stream_request.add(worker)
                    stream_workers.add(worker)
            # Keep the last valid mapping/cache if an invalid replacement fails.
            replace(b'invalid MMDB')
            for _ in range(30):
                assert http()[1] == 'updated'
                assert stream()[1] == 'updated'
            assert len(http_workers) == len(stream_workers) == 2, (http_workers, stream_workers)
        finally:
            process.terminate()
            process.wait(timeout=10)
        assert 'Reload MMDB' in (prefix / 'error.log').read_text()
        print(json.dumps({'http_workers': len(http_workers), 'stream_workers': len(stream_workers), 'ipv4_ipv6_realip': True, 'first_request_and_server_rewrite': True, 'same_ip_cache_invalidation': True, 'failed_reload_preserves_mapping': True}))


if __name__ == '__main__':
    main()
