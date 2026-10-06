# Auto-reload integration regression

Build Nginx and both dynamic modules from this checkout:

```sh
# Run in an unpacked Nginx source directory.
./configure --with-compat --with-http_realip_module --with-stream \
  --add-dynamic-module=/absolute/path/to/ngx_http_geoip2_module
make -j2
python3 /absolute/path/to/ngx_http_geoip2_module/tests/auto_reload.py \
  --nginx "$PWD/objs/nginx" --module-dir "$PWD/objs"
```

The test requires only Python's standard library, uses temporary files and
loopback ports, and starts a private Nginx process with two workers. It verifies:

- A lookup of an all-zero source address does not reuse an uninitialized cache.
- IPv4 and IPv6 RealIP processing continues after the reload handler.
- The first HTTP request after the check interval sees the replacement database,
  including a GeoIP variable evaluated during server rewrite.
- Repeated populated/empty atomic replacements invalidate same-IP caches in
  both HTTP and stream workers. Stream reload timing remains the LOG phase.
- Failed database reloads retain the previous valid mapping and cache.

The tiny MMDB fixtures contain synthetic `value` records, with no third-party
GeoIP data. `generate_fixtures.py` documents how to regenerate them; fixture
generation requires `mmdb-writer` and `netaddr`, but running the test does not.
