# backend/main.py
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from pydantic import BaseModel

app = FastAPI()

# CORS for REST endpoints (frontend served via http://localhost:8000 or file)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MongoDB
client = MongoClient(MONGO_URI)
db = client["cricket_auction"]
players_collection = db["players"]

# Player model (if you want to add via API later)
class Player(BaseModel):
    name: str
    role: str
    base_price: int
    image: str = ""

# --------- Sample load (if empty) ----------
def load_sample_players():
    if players_collection.count_documents({}) == 0:
        sample_players = [
            {"name":"Virat Kohli","role":"Batsman","base_price":50000,"image":"https://i.ibb.co/ZdS5KpR/virat.jpg"},
            {"name":"Rohit Sharma","role":"Batsman","base_price":45000,"image":"https://i.ibb.co/xFM3W2T/rohit.jpg"},
            {"name":"Jasprit Bumrah","role":"Bowler","base_price":40000,"image":"https://i.ibb.co/zHq2Nw7/bumrah.jpg"},
            {"name":"Hardik Pandya","role":"All-Rounder","base_price":42000,"image":"https://i.ibb.co/WgLwKLD/hardik.jpg"},
            {"name":"Ravindra Jadeja","role":"All-Rounder","base_price":38000,"image":"https://i.ibb.co/3WMLk9C/jadeja.jpg"}
        ]
        players_collection.insert_many(sample_players)
        print("Loaded sample players.")

load_sample_players()

# ---------- App state ----------
teams = {
    "Team A": {"budget": 100000},
    "Team B": {"budget": 100000},
    "Team C": {"budget": 100000},
    "Team D": {"budget": 100000},
}

current_bid = {"player": None, "highest_bid": 0, "team": None, "is_active": False}

# -------- WebSocket broadcast manager ----------
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self.lock:
            self.active_connections.append(websocket)

    async def disconnect(self, websocket: WebSocket):
        async with self.lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        # send concurrently
        async with self.lock:
            websockets = list(self.active_connections)
        coros = []
        for ws in websockets:
            coros.append(ws.send_json(message))
        if coros:
            await asyncio.gather(*coros, return_exceptions=True)

manager = ConnectionManager()

# ---------- REST endpoints ----------
@app.get("/")
def home():
    return {"message": "Cricket Auction API (with WebSocket) running."}

@app.get("/players/")
def get_players():
    return list(players_collection.find({}, {"_id": 0}))

@app.post("/add_player/")
def add_player(p: Player):
    players_collection.insert_one(p.dict())
    # broadcast players update
    asyncio.create_task(manager.broadcast({"type": "players_update", "players": list(players_collection.find({}, {"_id": 0}))}))
    return {"message": "Player added"}

@app.get("/budgets/")
def get_budgets():
    return teams

@app.get("/results/")
def get_results():
    return list(db["results"].find({}, {"_id": 0}))

@app.post("/clear_data/")
def clear_data():
    players_collection.delete_many({})
    db["results"].delete_many({})
    for t in teams:
        teams[t]["budget"] = 100000
    load_sample_players()
    # broadcast reset
    asyncio.create_task(manager.broadcast({"type":"clear_data"}))
    asyncio.create_task(manager.broadcast({"type":"players_update", "players": list(players_collection.find({}, {"_id": 0}))}))
    asyncio.create_task(manager.broadcast({"type":"budgets_update", "budgets": teams}))
    asyncio.create_task(manager.broadcast({"type":"results_update", "results": list(db['results'].find({}, {"_id":0}))}))
    return {"message":"All data cleared and sample players reloaded."}

# ---------- Bidding endpoints (these trigger broadcasts) ----------
@app.post("/start_bidding/")
def start_bidding(player_name: str):
    global current_bid
    current_bid = {"player": player_name, "highest_bid": 0, "team": None, "is_active": True}
    # broadcast start
    asyncio.create_task(manager.broadcast({
        "type":"start_bidding",
        "player": player_name,
        "highest_bid": 0
    }))
    return {"message": f"Bidding started for {player_name}"}

@app.post("/place_bid/")
def place_bid(team: str, amount: int):
    global current_bid
    if not current_bid["is_active"]:
        return {"error":"No active bidding right now"}
    if team not in teams:
        return {"error":"Invalid team name"}
    if amount > teams[team]["budget"]:
        return {"error": f"{team} does not have enough budget!"}
    if amount <= current_bid["highest_bid"]:
        return {"error":"Bid must be higher than current bid"}

    current_bid["highest_bid"] = amount
    current_bid["team"] = team
    # broadcast new bid
    asyncio.create_task(manager.broadcast({
        "type":"new_bid",
        "player": current_bid["player"],
        "highest_bid": amount,
        "team": team
    }))
    return {"message": f"{team} placed a bid of ₹{amount}"}

@app.post("/end_bidding/")
def end_bidding():
    global current_bid
    if not current_bid["is_active"]:
        return {"message":"No active bidding to end."}
    current_bid["is_active"] = False
    if current_bid["team"]:
        team = current_bid["team"]
        amount = current_bid["highest_bid"]
        teams[team]["budget"] -= amount
        db["results"].insert_one(current_bid)
        result_msg = {
            "type":"end_bidding",
            "player": current_bid["player"],
            "team": team,
            "highest_bid": amount
        }
        # broadcast result + budgets + results list
        asyncio.create_task(manager.broadcast(result_msg))
        asyncio.create_task(manager.broadcast({"type":"budgets_update", "budgets": teams}))
        asyncio.create_task(manager.broadcast({"type":"results_update", "results": list(db['results'].find({}, {"_id":0}))}))
        asyncio.create_task(manager.broadcast({"type":"players_update", "players": list(players_collection.find({}, {"_id": 0}))}))
        msg = f"{current_bid['player']} sold to {team} for ₹{amount}. Remaining budget: ₹{teams[team]['budget']}"
    else:
        asyncio.create_task(manager.broadcast({"type":"end_bidding", "player": current_bid["player"], "team": None, "highest_bid": 0}))
        msg = "No bids placed."
    # reset current_bid.player so next round can start differently if desired (we keep player stored)
    current_bid = {"player": None, "highest_bid": 0, "team": None, "is_active": False}
    return {"message": msg}

# ---------- WebSocket endpoint ----------
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # On new connection, send current snapshot
        await websocket.send_json({"type":"players_update", "players": list(players_collection.find({}, {"_id":0}))})
        await websocket.send_json({"type":"budgets_update", "budgets": teams})
        await websocket.send_json({"type":"results_update", "results": list(db['results'].find({}, {"_id":0}))})
        # optionally send current_bid if active
        if current_bid["is_active"]:
            await websocket.send_json({"type":"start_bidding", "player": current_bid["player"], "highest_bid": current_bid["highest_bid"]})
        while True:
            # we do not expect client messages, but keep connection alive
            data = await websocket.receive_text()
            # you could parse client-sent JSON and act upon it if needed
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception:
        await manager.disconnect(websocket)

