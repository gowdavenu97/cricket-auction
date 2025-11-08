// frontend/script.js
const API = "http://127.0.0.1:8000";

// local role state (admin / team / viewer) managed elsewhere in your UI
let userRole = localStorage.getItem("role") || "viewer"; // set by login controls when user logs in

// ------------- WebSocket connection -------------
let ws;
function initWebSocket() {
  ws = new WebSocket("ws://127.0.0.1:8000/ws");

  ws.onopen = () => {
    console.log("WebSocket connected.");
  };

  ws.onmessage = (evt) => {
    try {
      const msg = JSON.parse(evt.data);
      handleWSMessage(msg);
    } catch (e) {
      console.error("Invalid WS message", e);
    }
  };

  ws.onclose = () => {
    console.log("WebSocket closed, retrying in 2s...");
    setTimeout(initWebSocket, 2000); // auto-reconnect
  };

  ws.onerror = (err) => {
    console.error("WebSocket error", err);
    ws.close();
  };
}

initWebSocket();

// ------------- WS message handler -------------
function handleWSMessage(msg) {
  switch (msg.type) {
    case "players_update":
      // msg.players = []
      renderPlayers(msg.players);
      break;
    case "budgets_update":
      renderBudgets(msg.budgets);
      break;
    case "results_update":
      renderResults(msg.results);
      break;
    case "start_bidding":
      showStartBidding(msg);
      break;
    case "new_bid":
      updateCurrentBid(msg);
      break;
    case "end_bidding":
      showEndBidding(msg);
      break;
    case "clear_data":
      // reload UI fully
      fetchPlayersOnce();
      fetchBudgetsOnce();
      fetchResultsOnce();
      break;
    default:
      console.warn("Unknown WS message type", msg.type);
  }
}

// ------------- Helper REST fetchers for one-time calls -------------
async function fetchPlayersOnce() {
  const res = await fetch(`${API}/players/`);
  const players = await res.json();
  renderPlayers(players);
}
async function fetchBudgetsOnce() {
  const res = await fetch(`${API}/budgets/`);
  const budgets = await res.json();
  renderBudgets(budgets);
}
async function fetchResultsOnce() {
  const res = await fetch(`${API}/results/`);
  const results = await res.json();
  renderResults(results);
}

// ------------- Render functions (update DOM) -------------
function renderPlayers(players) {
  const container = document.getElementById("playerCards");
  if (!container) return;
  container.innerHTML = "";
  players.forEach(p => {
    const card = document.createElement("div");
    card.className = "col-md-3 player-card";
    card.innerHTML = `
      <img src="${p.image}" alt="${p.name}">
      <h5 class="mt-2">${p.name}</h5>
      <p>${p.role}</p>
      <p><strong>₹${p.base_price}</strong></p>
      <button class="btn btn-outline-primary" onclick="openBid('${p.name}','${p.role}','${p.base_price}','${p.image}')">Bid Now</button>
    `;
    container.appendChild(card);
  });
}

function renderBudgets(budgets) {
  const list = document.getElementById("budgetList");
  if (!list) return;
  list.innerHTML = "";
  for (const t in budgets) {
    const li = document.createElement("li");
    li.className = "list-group-item";
    li.textContent = `${t} — Remaining Budget: ₹${budgets[t].budget}`;
    list.appendChild(li);
  }
}

function renderResults(results) {
  const list = document.getElementById("resultsList");
  if (!list) return;
  list.innerHTML = "";
  if (!results || results.length === 0) {
    const li = document.createElement("li");
    li.className = "list-group-item text-center";
    li.textContent = "No players sold yet!";
    list.appendChild(li);
    return;
  }
  results.forEach(r => {
    const li = document.createElement("li");
    li.className = "list-group-item";
    li.textContent = `${r.player} → ${r.team} for ₹${r.highest_bid}`;
    list.appendChild(li);
  });
}

// ------------- Live bidding UI updates -------------
function showStartBidding(msg) {
  // msg: {type:"start_bidding", player, highest_bid}
  // display in modal if open, or show small toast (simple alert here)
  const info = `Bidding started for ${msg.player}. Current: ₹${msg.highest_bid}`;
  console.log(info);
  // update currentBid element if present
  const cur = document.getElementById("currentBid");
  if (cur) cur.textContent = `Current Bid: ₹${msg.highest_bid} (Player: ${msg.player})`;
}

function updateCurrentBid(msg) {
  // msg: {type:"new_bid", player, highest_bid, team}
  const cur = document.getElementById("currentBid");
  if (cur) cur.textContent = `Current Bid: ₹${msg.highest_bid} — ${msg.team}`;
  // show small notification
  // you can implement toast; for now console + optional alert (avoid annoying alerts)
  console.log(`New bid: ${msg.team} -> ₹${msg.highest_bid} for ${msg.player}`);
}

function showEndBidding(msg) {
  // msg: {type:"end_bidding", player, team, highest_bid}
  const cur = document.getElementById("currentBid");
  if (cur) cur.textContent = `No active bidding`;
  let text;
  if (msg.team) text = `${msg.player} sold to ${msg.team} for ₹${msg.highest_bid}`;
  else text = `No bids for ${msg.player}`;
  alert(text);
  // refresh budgets and results are broadcast separately, but ensure UI updated
  // fetchBudgetsOnce(); fetchResultsOnce(); // optional
}

// ------------- Modal + bidding actions (client -> REST) -------------
function openBid(name, role, price, image) {
  // populate modal fields
  document.getElementById("modalTitle").innerText = name;
  document.getElementById("modalRole").innerText = role;
  document.getElementById("modalPrice").innerText = `Base Price: ₹${price}`;
  document.getElementById("modalImage").src = image;

  // if admin starting bidding automatically (optional): admin users may start via REST
  // show modal
  const modal = new bootstrap.Modal(document.getElementById("bidModal"));
  modal.show();
  // we don't auto-start bidding unless admin calls start - depends on your UI.
}

async function startBiddingREST(playerName) {
  const res = await fetch(`${API}/start_bidding/?player_name=${encodeURIComponent(playerName)}`, { method: "POST" });
  return res.json();
}

async function placeBid() {
  const team = document.getElementById("teamName").value;
  const amount = parseInt(document.getElementById("bidAmount").value);
  if (!team || !amount) return alert("Enter team and amount");

  const res = await fetch(`${API}/place_bid/?team=${encodeURIComponent(team)}&amount=${amount}`, { method: "POST" });
  const data = await res.json();
  if (data.error) alert(data.error);
  else {
    // server broadcast will update everyone
    console.log(data.message);
  }
}

async function endBidding() {
  const res = await fetch(`${API}/end_bidding/`, { method: "POST" });
  const data = await res.json();
  if (data.message) console.log(data.message);
  // server broadcasts budgets/results
}

// ------------- Admin reset (REST) -------------
async function clearData() {
  if (!confirm("Reset auction?")) return;
  const res = await fetch(`${API}/clear_data/`, { method: "POST" });
  const data = await res.json();
  alert(data.message);
}

// ------------- Initialize (if page loaded without WS snapshot) -------------
fetchPlayersOnce();
fetchBudgetsOnce();
fetchResultsOnce();
