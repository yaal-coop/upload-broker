"""Create the layout, the key and the bucket of the development Garage.

Each step checks what Garage already has, so the script can run many times.
"""

import os

import httpx2

ADMIN_TOKEN = "dev-admin-token"
KEY_ID = "GK000000000000000000000000"
SECRET_KEY = "0" * 64
BUCKET = "uploads"


def found(response: httpx2.Response) -> bool:
    """Tell whether Garage has the requested object."""
    if response.status_code == httpx2.codes.NOT_FOUND:
        return False
    response.raise_for_status()
    return True


def assign_layout(client: httpx2.Client) -> None:
    """Give the node a role, unless it already has one."""
    layout = client.get("/v2/GetClusterLayout").raise_for_status().json()
    if layout["roles"]:
        return

    status = client.get("/v2/GetClusterStatus").raise_for_status().json()
    role = {
        "id": status["nodes"][0]["id"],
        "zone": "dev",
        "capacity": 10**9,
        "tags": [],
    }
    client.post("/v2/UpdateClusterLayout", json={"roles": [role]}).raise_for_status()
    client.post(
        "/v2/ApplyClusterLayout", json={"version": layout["version"] + 1}
    ).raise_for_status()


def import_key(client: httpx2.Client) -> None:
    """Import the development key, unless it exists."""
    if found(client.get("/v2/GetKeyInfo", params={"id": KEY_ID})):
        return

    client.post(
        "/v2/ImportKey",
        json={
            "accessKeyId": KEY_ID,
            "secretAccessKey": SECRET_KEY,
            "name": "upload-broker",
        },
    ).raise_for_status()


def create_bucket(client: httpx2.Client) -> str:
    """Create the bucket unless it exists, and return its id."""
    response = client.get("/v2/GetBucketInfo", params={"globalAlias": BUCKET})
    if not found(response):
        response = client.post(
            "/v2/CreateBucket", json={"globalAlias": BUCKET}
        ).raise_for_status()
    bucket_id: str = response.json()["id"]
    return bucket_id


def main() -> None:
    """Configure the Garage server at GARAGE_ADMIN_URL."""
    url = os.environ.get("GARAGE_ADMIN_URL", "http://127.0.0.1:3903")
    token = os.environ.get("GARAGE_ADMIN_TOKEN", ADMIN_TOKEN)
    with httpx2.Client(
        base_url=url, headers={"Authorization": f"Bearer {token}"}
    ) as client:
        assign_layout(client)
        import_key(client)
        bucket_id = create_bucket(client)
        client.post(
            "/v2/AllowBucketKey",
            json={
                "bucketId": bucket_id,
                "accessKeyId": KEY_ID,
                "permissions": {"read": True, "write": True, "owner": True},
            },
        ).raise_for_status()
    print(f"Garage is ready: bucket {BUCKET}, key {KEY_ID}")


if __name__ == "__main__":
    main()
