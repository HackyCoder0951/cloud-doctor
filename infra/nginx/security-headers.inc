# Security headers for every response nginx serves (TM-16). Included in EVERY location because nginx
# does not inherit add_header into a block that defines its own add_header.
#
# CSP (F1 in docs/dev/frontend/STATUS.md): a static export cannot use nonces, and Next.js emits inline
# <script> bootstrap/flight-data tags. They are allowed by SHA-256 hash ($cd_script_hashes, generated
# from the build into csp-script-hashes.conf), so script-src has NO 'unsafe-inline' and NO 'unsafe-eval'.
# The UI uses no inline styles, so style-src is 'self' only.
add_header Content-Security-Policy "default-src 'self'; script-src 'self' $cd_script_hashes; style-src 'self'; img-src 'self'; font-src 'self'; connect-src 'self'; manifest-src 'self'; worker-src 'none'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "no-referrer" always;
add_header Permissions-Policy "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=(), interest-cohort=()" always;
add_header Cross-Origin-Opener-Policy "same-origin" always;
add_header Cross-Origin-Resource-Policy "same-origin" always;
add_header X-Frame-Options "DENY" always;
# Over TLS also send (kept out of the default because this file is valid for plain HTTP too):
#   add_header Strict-Transport-Security "max-age=31536000" always;
