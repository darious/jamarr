import httpx
import asyncio

async def check():
    urls = {
        "Bastille": "https://i.scdn.co/image/ab6761610000e5ebf357b48e4344812b4e3c336f",
        "Bear's Den": "https://i.scdn.co/image/ab6761610000e5eb85509a33687cdd68b9ec36a4",
        "Maisie Peters": "https://i.scdn.co/image/ab6761610000e5ebdf349c55b3dce4a9c2da505d",
        "Biffy Clyro": "https://i.scdn.co/image/ab6761610000e5eb440fa32e555b94307d9f2e85"
    }
    
    async with httpx.AsyncClient() as client:
        for name, url in urls.items():
            try:
                resp = await client.get(url)
                print(f"{name}: {resp.status_code}, Length: {len(resp.content)}")
            except Exception as e:
                print(f"{name}: Error {e}")

if __name__ == "__main__":
    asyncio.run(check())
