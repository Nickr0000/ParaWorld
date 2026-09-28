import json
import math
import os
import random
import re

SAVE_DIR = "saves"
RES = ["food", "materials", "blueprints"]
ROLES = ["farmer", "gatherer", "guard", "scientist"]
TOOL_FOR = {"farmer": "farm", "gatherer": "gather", "guard": "firearm", "scientist": "structurizer"}
TOOL_NAMES = {"firearm": "Firearm", "farm": "Farmer's Tools", "gather": "Gatherer's Tools",
              "structurizer": "Structurizer"}
TOOL_MATS = {"firearm": 2, "farm": 2, "gather": 2, "structurizer": 4}
BUY = {"food": 5, "materials": 10, "blueprints": 25}
SELL = {"food": 2, "materials": 5, "blueprints": 12}
HIRE = {"farmer": 50, "gatherer": 60, "guard": 100, "scientist": 150}
MAX_TIER = 5
MAGNATE_GOAL = 1_000_000

POINTS = {
    "Library": dict(danger=2, food=0, materials=6, blueprints=14, space=12),
    "Science Laboratory": dict(danger=12, food=7, materials=6, blueprints=20, space=10),
    "Forest": dict(danger=8, food=16, materials=10, blueprints=2, space=18),
    "Abandoned Bunker": dict(danger=10, food=10, materials=10, blueprints=10, space=10),
    "Office Premises": dict(danger=3, food=6, materials=4, blueprints=8, space=14),
    "Residential Block": dict(danger=7, food=8, materials=10, blueprints=3, space=9),
}

# type -> (display name, space)
BUILDINGS = {
    "house": ("House", 1),
    "storage": ("Storage", 1),
    "lab": ("Laboratory", 1),
    "hydro": ("Hydroponics", 1),
    "mine": ("Mine", 1),
    "carrier": ("Intercolonial Carrier", 4),
    "station": ("Machine Station", 2),
    "hotel": ("Hotel", 1),
    "trade": ("Trading Post", 1),
    "gate": ("Gate", 10),
}
BONUS_BUILDING = {"blueprints": "lab", "food": "hydro", "materials": "mine"}


# ----------------------------------------------------------------- helpers
def ask_int(prompt, lo, hi):
    while True:
        s = input(f"{prompt} [{lo}-{hi}]: ").strip()
        if re.fullmatch(r"-?\d+", s) and lo <= int(s) <= hi:
            return int(s)
        print("Invalid input.")


def choose(title, options, back="Back"):
    print(f"\n=== {title} ===")
    for i, o in enumerate(options, 1):
        print(f" {i}. {o}")
    print(f" 0. {back}")
    n = ask_int(">", 0, len(options))
    return None if n == 0 else n - 1


def yes(prompt):
    return input(f"{prompt} (y/n): ").strip().lower().startswith("y")


def tool_price(kind, tier=1):
    return int(TOOL_MATS[kind] * BUY["materials"] * 1.5) * tier


def tool_label(t):
    return f"{TOOL_NAMES[t['type']]} T{t['tier']}"


def get_tier(o):
    return o["tier"] if isinstance(o, dict) else o.tier


def set_tier(o, v):
    if isinstance(o, dict):
        o["tier"] = v
    else:
        o.tier = v


# ----------------------------------------------------------------- classes
class Person:
    def __init__(self, role, founder=False, tool=None, project=None, busy=False):
        self.role = role
        self.founder = founder
        self.tool = tool
        self.project = project
        self.busy = busy

    def tier(self):
        t = self.tool
        return t["tier"] if t and t["type"] == TOOL_FOR[self.role] else 0

    def working(self):
        return (self.role == "scientist" and self.project is not None and not self.busy
                and self.tool is not None and self.tool["type"] == "structurizer")

    def label(self):
        tag = "[Founder] " if self.founder else ""
        tool = tool_label(self.tool) if self.tool else "no tool"
        job = f", project #{self.project}" if self.project is not None else ""
        return f"{tag}{self.role.title()} ({tool}{job})"

    def to_dict(self):
        return dict(role=self.role, founder=self.founder, tool=self.tool,
                    project=self.project, busy=self.busy)

    @staticmethod
    def from_dict(d):
        return Person(d["role"], d["founder"], d["tool"], d["project"], d.get("busy", False))


class Store:
    """Anything that holds resources, tools and people (the City and Colonies)."""

    def __init__(self):
        self.stock = {r: 0 for r in RES}
        self.tools = []
        self.people = []

    def store_dict(self):
        return dict(stock=self.stock, tools=self.tools, people=[p.to_dict() for p in self.people])

    def store_load(self, d):
        self.stock = d["stock"]
        self.tools = d["tools"]
        self.people = [Person.from_dict(p) for p in d["people"]]


class Building:
    def __init__(self, type_, tier=1, used=False):
        self.type = type_
        self.tier = tier
        self.used = used

    @property
    def name(self):
        return BUILDINGS[self.type][0]

    @property
    def space(self):
        return BUILDINGS[self.type][1]

    def to_dict(self):
        return dict(type=self.type, tier=self.tier, used=self.used)


class Colony(Store):
    def __init__(self, point):
        super().__init__()
        self.point = point
        self.ext = 0
        self.buildings = [Building("house"), Building("storage")]
        self.projects = []
        self.auto = {}  # destination colony -> {resource: amount per day}
        self.next_pid = 1

    # ---- derived values
    @property
    def P(self):
        return POINTS[self.point]

    def danger(self):
        return self.P["danger"] + self.ext + 5 * sum(1 for b in self.buildings if b.type == "gate")

    def space_total(self):
        return self.P["space"] + self.ext

    def space_used(self):
        return sum(b.space for b in self.buildings) + sum(p["space"] for p in self.projects)

    def space_free(self):
        return self.space_total() - self.space_used()

    def of_type(self, t):
        return [b for b in self.buildings if b.type == t]

    def max_prod(self, res):
        return self.P[res] + sum(1 + b.tier for b in self.of_type(BONUS_BUILDING[res]))

    def storage_cap(self):
        return sum(10 * (b.tier + 1) for b in self.of_type("storage"))

    def house_cap(self):
        return sum(b.tier + 1 for b in self.of_type("house"))

    def hotel_cap(self):
        return sum(b.tier + 1 for b in self.of_type("hotel"))

    def carrier_tier(self):
        c = self.of_type("carrier")
        return max(b.tier for b in c) if c else 0

    def has_gate5(self):
        return any(b.type == "gate" and b.tier >= 5 for b in self.buildings)

    # ---- people / tools
    def unequip(self, p):
        if p.tool:
            self.tools.append(p.tool)
            p.tool = None
        p.project = None

    def auto_equip(self):
        for p in self.people:
            if p.tool is None:
                cands = [t for t in self.tools if t["type"] == TOOL_FOR[p.role]]
                if cands:
                    best = max(cands, key=lambda t: t["tier"])
                    self.tools.remove(best)
                    p.tool = best

    def free_scientists(self):
        return [p for p in self.people if p.role == "scientist" and not p.busy and not p.working()]

    # ---- daily simulation
    def process_day(self, game):
        log = []
        # construction
        workers = {}
        for p in self.people:
            if p.working():
                workers[p.project] = workers.get(p.project, 0) + 1
        for pr in list(self.projects):
            pr["done"] += workers.get(pr["id"], 0)
            if pr["done"] >= pr["total"]:
                self.projects.remove(pr)
                self.buildings.append(Building(pr["type"], pr["tier"]))
                for p in self.people:
                    if p.project == pr["id"]:
                        p.project = None
                log.append(f"Construction finished: {BUILDINGS[pr['type']][0]} (T{pr['tier']}).")
        # production
        prod = {r: 0 for r in RES}
        guard_power = 0
        for p in self.people:
            if p.busy:
                continue
            if p.role == "farmer":
                prod["food"] += 1 + p.tier()
            elif p.role == "gatherer":
                prod["materials"] += 1 + p.tier()
            elif p.role == "guard":
                guard_power += p.tier()
            elif p.role == "scientist" and not p.working():
                prod["blueprints"] += 1
        made = []
        for r in RES:
            amt = min(prod[r], self.max_prod(r))
            self.stock[r] += amt
            made.append(f"{amt} {r}")
        log.append("Produced: " + ", ".join(made) + ".")
        # eating
        n = len(self.people)
        eat = min(n, self.stock["food"])
        self.stock["food"] -= eat
        deficit = n - eat
        if deficit > 0:
            victims = [p for p in self.people if not p.founder and p.role != "farmer"]
            random.shuffle(victims)
            dead = victims[:deficit]
            for p in dead:
                self.people.remove(p)
            log.append(f"FAMINE! Not enough food. {len(dead)} people left the colony.")
        # hotels
        guests = min(self.hotel_cap(), len(self.people))
        fed = min(guests, self.stock["food"])
        if fed:
            self.stock["food"] -= fed
            game.coins += 10 * fed
            log.append(f"Hotel: {fed} guests paid {10 * fed} coins.")
        # attack
        d = self.danger()
        if d > 0:
            net = d - guard_power
            if net <= 0:
                log.append(f"Attack (tier {d}) repelled!")
                kind = random.choice(["coins", "materials", "blueprints"])
                if kind == "coins":
                    game.coins += 10 * d
                    log.append(f"Reward: {10 * d} coins.")
                elif kind == "materials":
                    self.stock["materials"] += d
                    log.append(f"Reward: {d} materials.")
                else:
                    amt = max(1, d // 3)
                    self.stock["blueprints"] += amt
                    log.append(f"Reward: {amt} blueprints.")
            else:
                lost = 0
                for _ in range(net):
                    guards = [p for p in self.people if p.role == "guard" and not p.founder]
                    others = [p for p in self.people if p.role != "guard" and not p.founder]
                    pool = guards or others
                    if not pool:
                        break
                    self.people.remove(random.choice(pool))
                    lost += 1
                log.append(f"ATTACK! Danger {d} vs defense {guard_power}. {lost} people lost.")
        # housing and storage limits
        nonf = [p for p in self.people if not p.founder]
        excess = len(nonf) - self.house_cap() - self.hotel_cap() * 0  # hotels counted in house_cap below
        excess = len(nonf) - (self.house_cap() + self.hotel_cap())
        if excess > 0:
            for p in random.sample(nonf, excess):
                self.people.remove(p)
            log.append(f"{excess} people vanished (no housing).")
        cap = self.storage_cap()
        for r in RES:
            if self.stock[r] > cap:
                log.append(f"{self.stock[r] - cap} {r} vanished (no storage).")
                self.stock[r] = cap
        # reset daily flags
        for p in self.people:
            p.busy = False
        for b in self.buildings:
            b.used = False
        return log

    # ---- persistence
    def to_dict(self):
        d = self.store_dict()
        d.update(point=self.point, ext=self.ext, buildings=[b.to_dict() for b in self.buildings],
                 projects=self.projects, auto=self.auto, next_pid=self.next_pid)
        return d

    @staticmethod
    def from_dict(d):
        c = Colony(d["point"])
        c.store_load(d)
        c.ext = d["ext"]
        c.buildings = [Building(**b) for b in d["buildings"]]
        c.projects = d["projects"]
        c.auto = d["auto"]
        c.next_pid = d["next_pid"]
        return c


class Game:
    def __init__(self, name, difficulty):
        self.name = name
        self.difficulty = difficulty
        self.coins = 500
        self.day = 1
        self.city = Store()
        for _ in range(difficulty):
            self.city.people.append(Person("gatherer", founder=True))
        self.shop_people = {r: 0 for r in ROLES}
        self.restock()
        self.colonies = {}
        self.transfers = []
        self.magnate_done = False
        self.gate_done = False

    # ---- persistence
    @staticmethod
    def path(name):
        return os.path.join(SAVE_DIR, re.sub(r"[^\w\-]", "_", name) + ".json")

    def save(self):
        os.makedirs(SAVE_DIR, exist_ok=True)
        data = dict(name=self.name, difficulty=self.difficulty, coins=self.coins, day=self.day,
                    city=self.city.store_dict(), shop=self.shop_people,
                    colonies=[c.to_dict() for c in self.colonies.values()],
                    transfers=self.transfers, magnate=self.magnate_done, gate=self.gate_done)
        with open(self.path(self.name), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
        print("Game saved.")

    @staticmethod
    def load(fname):
        with open(os.path.join(SAVE_DIR, fname), encoding="utf-8") as f:
            d = json.load(f)
        g = Game(d["name"], d["difficulty"])
        g.coins, g.day = d["coins"], d["day"]
        g.city = Store()
        g.city.store_load(d["city"])
        g.shop_people = d["shop"]
        g.colonies = {c["point"]: Colony.from_dict(c) for c in d["colonies"]}
        g.transfers = d["transfers"]
        g.magnate_done, g.gate_done = d["magnate"], d["gate"]
        return g

    # ---- shop
    def restock(self):
        for r in ROLES:
            self.shop_people[r] = min(8, self.shop_people[r] + random.randint(0, 2))

    def trade_resources(self, stock):
        """Buy/sell resources between the player's coins and a stock (city or colony)."""
        while True:
            print(f"\nCoins: {self.coins} | Stock: " + ", ".join(f"{r} {stock[r]}" for r in RES))
            i = choose("TRADE", [f"Buy {r} ({BUY[r]}c)" for r in RES] + [f"Sell {r} ({SELL[r]}c)" for r in RES])
            if i is None:
                return
            r = RES[i % 3]
            if i < 3:
                n = ask_int(f"Buy how many {r}", 0, self.coins // BUY[r])
                self.coins -= n * BUY[r]
                stock[r] += n
            else:
                n = ask_int(f"Sell how many {r}", 0, stock[r])
                self.coins += n * SELL[r]
                stock[r] -= n

    def shop(self):
        while True:
            print(f"\nCoins: {self.coins}")
            i = choose("SHOP", ["Buy/sell resources", "Buy tools", "Sell tools", "Hire people"], "Leave")
            if i is None:
                return
            if i == 0:
                self.trade_resources(self.city.stock)
            elif i == 1:
                kinds = list(TOOL_NAMES)
                j = choose("BUY TOOLS", [f"{TOOL_NAMES[k]} ({tool_price(k)}c)" for k in kinds])
                if j is not None:
                    if self.coins >= tool_price(kinds[j]):
                        self.coins -= tool_price(kinds[j])
                        self.city.tools.append({"type": kinds[j], "tier": 1})
                    else:
                        print("Not enough coins.")
            elif i == 2:
                ts = self.city.tools
                j = choose("SELL TOOLS", [f"{tool_label(t)} ({tool_price(t['type'], t['tier']) // 2}c)" for t in ts])
                if j is not None:
                    t = ts.pop(j)
                    self.coins += tool_price(t["type"], t["tier"]) // 2
            else:
                j = choose("HIRE", [f"{r.title()} - {HIRE[r]}c (available: {self.shop_people[r]})" for r in ROLES])
                if j is not None:
                    r = ROLES[j]
                    n = ask_int("How many", 0, min(self.shop_people[r], self.coins // HIRE[r]))
                    self.coins -= n * HIRE[r]
                    self.shop_people[r] -= n
                    self.city.people += [Person(r) for _ in range(n)]

    # ---- moving items between city and colonies
    def move(self, src, dst):
        k = choose("MOVE WHAT?", ["Resources", "Tools", "People"])
        if k == 0:
            r = choose("Resource", [f"{r} ({src.stock[r]})" for r in RES])
            if r is not None:
                n = ask_int("Amount", 0, src.stock[RES[r]])
                src.stock[RES[r]] -= n
                dst.stock[RES[r]] += n
        elif k == 1:
            j = choose("Tool", [tool_label(t) for t in src.tools])
            if j is not None:
                dst.tools.append(src.tools.pop(j))
        elif k == 2:
            j = choose("Person", [p.label() for p in src.people])
            if j is not None:
                p = src.people.pop(j)
                p.project = None
                dst.people.append(p)

    def move_all(self, src, dst):
        for r in RES:
            dst.stock[r] += src.stock[r]
            src.stock[r] = 0
        dst.tools += src.tools
        src.tools = []
        for p in src.people:
            p.project = None
        dst.people += src.people
        src.people = []
        print("Everything was moved.")

    # ---- colony UI
    def show_colony(self, c):
        print(f"\n--- {c.point} --- Day {self.day} | Coins {self.coins}")
        print(f"Danger {c.danger()} | Space free {c.space_free()}/{c.space_total()}")
        cap = c.storage_cap()
        print("Stock: " + ", ".join(f"{r} {c.stock[r]}/{cap}" for r in RES))
        print("Max production/day: " + ", ".join(f"{r} {c.max_prod(r)}" for r in RES))
        print("Buildings: " + ", ".join(f"{b.name} T{b.tier}" for b in c.buildings))
        for pr in c.projects:
            print(f"  Project #{pr['id']}: {BUILDINGS[pr['type']][0]} T{pr['tier']} "
                  f"{pr['done']}/{pr['total']} work")
        counts = {r: sum(1 for p in c.people if p.role == r) for r in ROLES}
        print("People: " + ", ".join(f"{r} {n}" for r, n in counts.items())
              + f" | Housing {c.house_cap() + c.hotel_cap()}, Danger defense "
              + str(sum(p.tier() for p in c.people if p.role == 'guard')))
        print(f"Unused tools: {len(c.tools)}")

    def colony_menu(self, c):
        while True:
            self.show_colony(c)
            opts = ["Manage people", "Construction", "Upgrades (Machine Station)",
                    "Move items to/from City", "Trading Post", "Carrier", "End day"]
            i = choose(f"COLONY: {c.point}", opts, "Return to City")
            if i is None:
                return
            if i == 0:
                self.people_menu(c)
            elif i == 1:
                self.build_menu(c)
            elif i == 2:
                self.upgrade_menu(c)
            elif i == 3:
                j = choose("LOGISTICS", ["City -> Colony", "Colony -> City",
                                         "ALL City -> Colony", "ALL Colony -> City"])
                if j == 2:
                    self.move_all(self.city, c)
                elif j == 3:
                    self.move_all(c, self.city)
                while j in (0, 1):
                    self.move(self.city, c) if j == 0 else self.move(c, self.city)
                    if not yes("Move something else?"):
                        break
            elif i == 4:
                if c.of_type("trade"):
                    self.trade_resources(c.stock)
                else:
                    print("Build a Trading Post first.")
            elif i == 5:
                self.carrier_menu(c)
            elif i == 6:
                if self.end_day():
                    return "quit"

    def people_menu(self, c):
        while True:
            i = choose("PEOPLE", ["List people", "Auto-equip everyone", "Unequip everyone",
                                  "Change a Founder's role", "Assign scientists to a project"])
            if i is None:
                return
            if i == 0:
                for n, p in enumerate(c.people, 1):
                    print(f" {n}. {p.label()}")
            elif i == 1:
                c.auto_equip()
                print("Done.")
            elif i == 2:
                for p in c.people:
                    c.unequip(p)
            elif i == 3:
                fs = [p for p in c.people if p.founder]
                j = choose("Founder", [p.label() for p in fs])
                if j is not None:
                    r = choose("New role", [r.title() for r in ROLES])
                    if r is not None:
                        c.unequip(fs[j])
                        fs[j].role = ROLES[r]
            elif i == 4:
                if not c.projects:
                    print("No construction projects.")
                    continue
                sc = [p for p in c.people if p.role == "scientist" and p.tool and p.tool["type"] == "structurizer"]
                if not sc:
                    print("No scientists with a Structurizer.")
                    continue
                pr = choose("Project", [f"#{p['id']} {BUILDINGS[p['type']][0]}" for p in c.projects])
                if pr is None:
                    continue
                pid = c.projects[pr]["id"]
                if yes("Assign ALL scientists with Structurizers?"):
                    for p in sc:
                        p.project = pid
                else:
                    j = choose("Scientist", [p.label() for p in sc])
                    if j is not None:
                        sc[j].project = pid

    def build_menu(self, c):
        keys = list(BUILDINGS)
        labels = []
        for k in keys:
            n, s = BUILDINGS[k]
            labels.append(f"{n} - space {s}, {5 * s} materials, {s * 2} work-days")
        labels.append("Expansion - +1 space, +1 danger, 5 materials (instant)")
        i = choose(f"BUILD (free space {c.space_free()}, materials {c.stock['materials']})", labels)
        if i is None:
            return
        if i == len(keys):
            if c.stock["materials"] < 5:
                print("Not enough materials.")
                return
            c.stock["materials"] -= 5
            c.ext += 1
            print("Territory expanded.")
            return
        k = keys[i]
        s = BUILDINGS[k][1]
        if s > c.space_free():
            print("Not enough space.")
        elif c.stock["materials"] < 5 * s:
            print("Not enough materials.")
        else:
            c.stock["materials"] -= 5 * s
            c.projects.append(dict(id=c.next_pid, type=k, tier=5 if k == "gate" else 1,
                                   total=s * 2, done=0, space=s))
            print(f"Project #{c.next_pid} started. Assign scientists with Structurizers to it.")
            c.next_pid += 1

    def upgrade_menu(self, c):
        stations = [b for b in c.of_type("station") if not b.used]
        if not stations:
            print("You need an unused Machine Station.")
            return
        targets = [(f"{b.name} T{b.tier}", b) for b in c.buildings]
        targets += [(f"{tool_label(t)} (stored)", t) for t in c.tools]
        targets += [(f"{tool_label(p.tool)} (equipped, {p.role})", p.tool) for p in c.people if p.tool]
        i = choose("UPGRADE (cost: new tier in blueprints and in scientists)",
                   [f"{lbl} -> T{get_tier(o) + 1}" for lbl, o in targets])
        if i is None:
            return
        o = targets[i][1]
        new = get_tier(o) + 1
        if new > MAX_TIER:
            print("Already at max tier.")
            return
        st = next((s for s in stations if (o is s and new <= s.tier + 1) or (o is not s and new <= s.tier)), None)
        if st is None:
            print("No available Station has a high enough tier.")
            return
        free = c.free_scientists()
        if c.stock["blueprints"] < new:
            print(f"Need {new} blueprints.")
        elif len(free) < new:
            print(f"Need {new} free scientists (have {len(free)}).")
        else:
            c.stock["blueprints"] -= new
            for p in free[:new]:
                p.busy = True
            set_tier(o, new)
            st.used = True
            print(f"Upgraded to tier {new}.")

    def carrier_menu(self, c):
        if not c.of_type("carrier"):
            print("Build an Intercolonial Carrier first.")
            return
        others = [x for x in self.colonies.values() if x is not c and x.of_type("carrier")]
        if not others:
            print("No other colony has a Carrier.")
            return
        i = choose("CARRIER", ["Send resources now", "Set daily automatic shipment"])
        if i is None:
            return
        j = choose("Destination", [f"{x.point} ({self.travel_days(c, x)} days)" for x in others])
        if j is None:
            return
        dest = others[j]
        r = choose("Resource", [f"{r} ({c.stock[r]})" for r in RES])
        if r is None:
            return
        res = RES[r]
        if i == 0:
            n = ask_int("Amount", 0, c.stock[res])
            if n:
                c.stock[res] -= n
                self.transfers.append(dict(dest=dest.point, arrive=self.day + self.travel_days(c, dest),
                                           res={res: n}))
                print("Shipment sent.")
        else:
            n = ask_int("Amount per day (0 to cancel)", 0, 999)
            c.auto.setdefault(dest.point, {})[res] = n

    @staticmethod
    def travel_days(a, b):
        return max(1, a.danger() + b.danger() - a.carrier_tier() - b.carrier_tier())

    # ---- day cycle
    def end_day(self):
        print(f"\n========== END OF DAY {self.day} ==========")
        for c in self.colonies.values():
            print(f"\n[{c.point}]")
            for line in c.process_day(self):
                print(" ", line)
        # automatic shipments
        for c in self.colonies.values():
            for dname, amounts in c.auto.items():
                d = self.colonies.get(dname)
                if not d or not c.of_type("carrier") or not d.of_type("carrier"):
                    continue
                ship = {}
                for r, n in amounts.items():
                    q = min(n, c.stock[r])
                    if q > 0:
                        c.stock[r] -= q
                        ship[r] = q
                if ship:
                    self.transfers.append(dict(dest=dname, arrive=self.day + self.travel_days(c, d), res=ship))
        self.day += 1
        for t in list(self.transfers):
            if t["arrive"] <= self.day:
                d = self.colonies.get(t["dest"])
                if d:
                    for r, n in t["res"].items():
                        d.stock[r] += n
                    print(f"A shipment arrived at {d.point}: {t['res']}")
                self.transfers.remove(t)
        self.restock()
        return self.check_endings()

    def check_endings(self):
        if self.coins >= MAGNATE_GOAL and not self.magnate_done:
            self.magnate_done = True
            print("\n*** ENDING: MAGNATE ***")
            print("You became a magnate and decided you no longer need these colonies.")
            if yes("Finish the game?"):
                return True
        if self.colonies and not self.gate_done and all(c.has_gate5() for c in self.colonies.values()):
            self.gate_done = True
            print("\n*** ENDING: TERRITORY EXPANSION ***")
            print("Tier 5 Gates stand in every colony. The parallel worlds are yours.")
            if yes("Finish the game?"):
                return True
        return False

    # ---- city UI
    def city_menu(self):
        while True:
            print(f"\n##### CITY - {self.name} (difficulty {self.difficulty}) | Day {self.day} | Coins {self.coins} #####")
            print("City stock: " + ", ".join(f"{r} {self.city.stock[r]}" for r in RES)
                  + f" | tools {len(self.city.tools)} | people {len(self.city.people)}")
            i = choose("CITY", ["Shop", "Teleport points", "City inventory", "End day", "Save game"],
                       "Save & quit")
            if i is None:
                self.save()
                return
            if i == 0:
                self.shop()
            elif i == 1:
                names = list(POINTS)
                labels = []
                for n in names:
                    p = POINTS[n]
                    tag = "[COLONY] " if n in self.colonies else ""
                    labels.append(f"{tag}{n} - Danger {p['danger']}, Food {p['food']}, Materials {p['materials']}, "
                                  f"Blueprints {p['blueprints']}, Space {p['space']}")
                j = choose("TELEPORT POINTS", labels)
                if j is not None:
                    if names[j] not in self.colonies:
                        self.colonies[names[j]] = Colony(names[j])
                        print(f"New colony founded at {names[j]}!")
                    if self.colony_menu(self.colonies[names[j]]) == "quit":
                        return
            elif i == 2:
                print("Tools: " + (", ".join(tool_label(t) for t in self.city.tools) or "none"))
                for n, p in enumerate(self.city.people, 1):
                    print(f" {n}. {p.label()}")
            elif i == 3:
                if self.end_day():
                    return
            elif i == 4:
                self.save()


# ----------------------------------------------------------------- start
def list_saves():
    out = []
    if os.path.isdir(SAVE_DIR):
        for f in sorted(os.listdir(SAVE_DIR)):
            if f.endswith(".json"):
                try:
                    with open(os.path.join(SAVE_DIR, f), encoding="utf-8") as fh:
                        d = json.load(fh)
                    out.append((f, f"{d['name']} (difficulty {d['difficulty']}, day {d['day']}, {d['coins']} coins)"))
                except (OSError, ValueError, KeyError):
                    pass
    return out


def main():
    print("=== COLONY ORGANIZER ===")
    while True:
        i = choose("MAIN MENU", ["Load game", "New game"], "Exit")
        if i is None:
            return
        if i == 0:
            saves = list_saves()
            if not saves:
                print("No saves found.")
                continue
            j = choose("SAVES", [s[1] for s in saves])
            if j is not None:
                Game.load(saves[j][0]).city_menu()
        else:
            name = input("Enter your alias: ").strip()
            if not name:
                continue
            if os.path.exists(Game.path(name)) and not yes("A save with this name exists. Overwrite?"):
                continue
            diff = ask_int("Difficulty (0 = hardcore, 10 = just run through)", 0, 10)
            Game(name, diff).city_menu()


if __name__ == "__main__":
    main()
