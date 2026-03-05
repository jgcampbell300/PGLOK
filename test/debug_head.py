import requests

url = "https://cdn.projectgorgon.com/v461/data/"  # replace with real file URL
r = requests.head(url, allow_redirects=True, timeout=30)

print("status:", r.status_code)
print("ETag:", r.headers.get("ETag"))
print("Last-Modified:", r.headers.get("Last-Modified"))
print("Content-Length:", r.headers.get("Content-Length"))
print("all headers:", dict(r.headers))