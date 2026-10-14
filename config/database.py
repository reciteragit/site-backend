from django.core.exceptions import ImproperlyConfigured
import dj_database_url

def database_settings(environ, base_dir, debug):
    url = environ.get("DATABASE_URL") or environ.get("POSTGRES_URL")
    if url:
        config = dj_database_url.parse(
            url, conn_max_age=0,
            ssl_require=environ.get("DATABASE_SSL_REQUIRED", "true").lower() == "true",
        )
        if not debug and config["ENGINE"] != "django.db.backends.postgresql":
            raise ImproperlyConfigured("Production requires a PostgreSQL connection")
        config["DISABLE_SERVER_SIDE_CURSORS"] = True
        return {"default": config}
    if debug:
        return {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": base_dir / "db.sqlite3"}}
    raise ImproperlyConfigured("DATABASE_URL or POSTGRES_URL is required in production")
