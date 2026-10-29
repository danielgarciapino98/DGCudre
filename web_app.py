import os, sys, tempfile, secrets
import math
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from database import Database, BusinessError
from config import BASE_DIR, config
from licensing import device_activation_id, validate_stored_license
from ia.llama_client import LlamaClient, LlamaError
from ia.agent import Agent

app = FastAPI(title="DGCuadres Web", version="2.0-web")
app.mount("/static", StaticFiles(directory=str(ROOT / "web" / "static")), name="static")
DB_PATH = config.get("General", "db_path", "dgcuadres_pos.db")
if not os.path.isabs(DB_PATH): DB_PATH = str(Path(BASE_DIR) / DB_PATH)

_web_tokens = {}
_web_tokens_lock = threading.Lock()
_PUBLIC_PATHS = {
    "/", "/manifest.webmanifest", "/api/access/state", "/api/access/license",
    "/api/access/register", "/api/access/login",
}

@app.middleware("http")
async def require_authenticated_admin(request: Request, call_next):
    path = request.url.path
    if path in _PUBLIC_PATHS or path.startswith("/static/"):
        return await call_next(request)

    authorization = request.headers.get("authorization", "")
    token = authorization[7:].strip() if authorization.startswith("Bearer ") else ""
    now = time.monotonic()
    with _web_tokens_lock:
        for expired in [key for key, value in _web_tokens.items() if value["expires_at"] <= now]:
            del _web_tokens[expired]
        authenticated = bool(token and token in _web_tokens)
    if not authenticated:
        return JSONResponse({"detail": "Inicie sesión como administrador."}, status_code=401)

    d = db()
    try:
        license_row = d.get_license()
    finally:
        d.close()
    if not license_row:
        return JSONResponse({"detail": "Debe activar una licencia."}, status_code=423)
    try:
        validate_stored_license(license_row)
    except BusinessError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=423)
    return await call_next(request)

def db(): return Database(DB_PATH)
def ok(fn):
    d=db()
    try: return fn(d)
    except BusinessError as e: raise HTTPException(400,str(e))
    finally: d.close()

def valid_stored_license(d):
    row = d.get_license()
    if not row:
        raise BusinessError("Debe activar una licencia.")
    return validate_stored_license(row)

def create_web_token(user):
    token = secrets.token_urlsafe(32)
    with _web_tokens_lock:
        _web_tokens[token] = {
            "admin_id": user["id"],
            "username": user["username"],
            "expires_at": time.monotonic() + 12 * 60 * 60,
        }
    return token

def web_access_response(user):
    return {"token": create_web_token(user), "username": user["username"]}

def detail(d, sid):
    s=d.get_shift_by_id(int(sid))
    if not s: raise BusinessError("No existe ese turno.")
    s=dict(s)
    s["items"] = d.get_shift_items(int(sid))
    for item in s["items"]:
        for field in ("initial_stock", "entries", "traslados", "roturas",
                      "final_stock", "sold_qty"):
            item[field] = round(item[field], 2)
    s["expenses"]=d.get_shift_expenses(int(sid)); s["cash_counts"]=d.get_shift_cash_counts(int(sid)); s["opening_cash_counts"]=d.get_shift_opening_cash_counts(int(sid)); s["currency_receipts"]=d.get_shift_currency_receipts(int(sid)); s["totals"]=d.compute_shift_totals(int(sid)); return s

class Product(BaseModel): point_id:int; code:str; name:str; unit:str="unidad"; cost_price:float=0; sale_price:float=0; stock_current:float=0; expiration_date:Optional[str]=None
class ProductUpdate(Product): product_id:int
class Point(BaseModel): name:str
class Worker(BaseModel):
    name:str
    role:str=""
    contact:str=""
    compensation_type:str="mensual"
    compensation_amount:float=0
class ShiftOpen(BaseModel):
    point_id:int
    cashier:str
    supervisor:str
    fondo_cambio:float=0
    opening_counts:Optional[dict]=None
    foreign_currency_code:Optional[str]=None
    exchange_rate:Optional[float]=None
    exchange_rate_usd:Optional[float]=None
    exchange_rate_eur:Optional[float]=None
class ItemUpdate(BaseModel): item_id:int; initial_st:float; entries:float; traslados:float; roturas:float; final_st:float
class Expense(BaseModel):
    shift_id:int
    persona:str=""
    concepto:str
    importe:float
    category:str="Operativo"
    worker_name:Optional[str]=None
class Cash(BaseModel):
    shift_id:int
    counts:dict
    transfer_total:float=0
    foreign_currency_total:float=0
    currency_totals:dict[str,float]=Field(default_factory=dict)
class ConfigData(BaseModel):
    nombre:str
    direccion:str
    telefono:str
    moneda:str
    ia_url:str
    ia_modelo:str=""
    ia_api_key:Optional[str]=None
    ia_clear_api_key:bool=False
    ia_enabled:Optional[bool]=None
    stock_minimo:int=5
    foreign_currency_code:Optional[str]=None
    exchange_rate:Optional[float]=None
    exchange_rate_usd:Optional[float]=None
    exchange_rate_eur:Optional[float]=None

class AccessCredentials(BaseModel):
    username:str
    password:str

class LicenseActivation(BaseModel):
    code:str

@app.get("/", response_class=HTMLResponse)
def home():
    page = (ROOT/"web"/"templates"/"index.html").read_text(encoding="utf-8")
    return page.replace("</head>", '<link rel="stylesheet" href="/static/ux.css"></head>')

@app.get("/api/access/state")
def access_state():
    d=db()
    try:
        license_row = d.get_license()
        valid_license = None
        license_error = ""
        if license_row:
            try:
                valid_license = validate_stored_license(license_row)
            except BusinessError as exc:
                license_error = str(exc)
        return {
            "licensed": valid_license is not None,
            "customer": valid_license["customer"] if valid_license else "",
            "expires_on": valid_license["expires_on"] if valid_license else "",
            "license_error": license_error,
            "activation_id": device_activation_id(),
            "administrator_registered": d.has_administrator(),
        }
    finally:
        d.close()

@app.post("/api/access/license")
def activate_license(x:LicenseActivation):
    d=db()
    try:
        try:
            d.activate_license(x.code)
        except BusinessError as exc:
            raise HTTPException(400, str(exc)) from exc
    finally:
        d.close()
    return {"ok":True}

@app.post("/api/access/register")
def register_admin(x:AccessCredentials):
    d=db()
    try:
        try:
            valid_stored_license(d)
            d.register_administrator(x.username, x.password)
            user = d.authenticate_administrator(x.username, x.password)
        except BusinessError as exc:
            raise HTTPException(400, str(exc)) from exc
    finally:
        d.close()
    return web_access_response(user)

@app.post("/api/access/login")
def login_admin(x:AccessCredentials):
    d=db()
    try:
        try:
            valid_stored_license(d)
        except BusinessError as exc:
            raise HTTPException(423, str(exc)) from exc
        user = d.authenticate_administrator(x.username, x.password)
    finally:
        d.close()
    if user is None:
        raise HTTPException(401, "El usuario o la contraseña no son correctos.")
    return web_access_response(user)

@app.get("/manifest.webmanifest")
def manifest(): return JSONResponse({"name":"DGCuadres/POS","short_name":"DG POS","start_url":"/","display":"standalone","background_color":"#07111f","theme_color":"#0b1220","icons":[{"src":"/static/icon.png","sizes":"512x512","type":"image/png"}]})

@app.get("/api/bootstrap")
def bootstrap():
    d=db()
    try:
        pts=d.get_points(False); workers=d.get_workers(); den=d.get_denominations()
        return {"points":pts,"workers":workers,"denominations":den,"config":{"nombre":config.get('Empresa','nombre',''),"direccion":config.get('Empresa','direccion',''),"telefono":config.get('Empresa','telefono',''),"moneda":config.get('General','moneda','$'),"foreign_currency_code":config.get('General','foreign_currency_code','USD'),"exchange_rate":config.getfloat('General','exchange_rate',1),"exchange_rate_usd":config.getfloat('General','exchange_rate_usd',1),"exchange_rate_eur":config.getfloat('General','exchange_rate_eur',1),"ia_enabled":config.ia_enabled,"ia_url":config.get('IA','url','http://127.0.0.1:8081'),"ia_modelo":config.get('IA','modelo',''),"ia_api_key_configured":bool(config.get('IA','api_key','').strip()),"stock_minimo":config.stock_minimo}}
    finally:d.close()

@app.get("/api/dashboard")
def dashboard(point_id:int):
    def f(d):
        p=d.get_point(point_id); sh=d.get_active_shift(point_id); items=d.get_products(point_id)
        totals=d.compute_shift_totals(sh['id']) if sh else None
        low=[x for x in items if x['stock_current']<=config.stock_minimo]
        return {"point":p,"active_shift":detail(d,sh['id']) if sh else None,"low_stock":low,"totals":totals}
    return ok(f)

@app.get("/api/products")
def products(point_id:int, active:bool=True): return ok(lambda d:d.get_products(point_id,active))
@app.post("/api/products")
def add_product(x:Product): return ok(lambda d:(d.add_product(**x.model_dump()),{"ok":True})[1])
@app.put("/api/products/{pid}")
def update_product(pid:int,x:Product):
    def save(d):
        existing = d.get_product(pid)
        if not existing: raise BusinessError("No existe ese producto.")
        expiration_date = existing["expiration_date"] if x.expiration_date is None else x.expiration_date or None
        d.update_product(pid,x.code,x.name,x.unit,x.cost_price,x.sale_price,x.stock_current,expiration_date)
        return {"ok":True}
    return ok(save)
@app.delete("/api/products/{pid}")
def delete_product(pid:int): return ok(lambda d:(d.deactivate_product(pid),{"ok":True})[1])

@app.get("/api/points")
def points(active:bool=False): return ok(lambda d:d.get_points(active))
@app.post("/api/points")
def add_point(x:Point): return ok(lambda d:(d.add_point(x.name),{"ok":True})[1])
@app.put("/api/points/{pid}")
def rename_point(pid:int,x:Point): return ok(lambda d:(d.rename_point(pid,x.name),{"ok":True})[1])
@app.post("/api/points/{pid}/active")
def active_point(pid:int,active:bool): return ok(lambda d:(d.set_point_active(pid,active),{"ok":True})[1])
@app.delete("/api/points/{pid}")
def delete_point(pid:int): return ok(lambda d:(d.delete_point(pid),{"ok":True})[1])

@app.get("/api/workers")
def workers(): return ok(lambda d:d.get_workers())
@app.get("/api/workers/details")
def workers_details(): return ok(lambda d:[d.get_worker(name) for name in d.get_workers()])
@app.post("/api/workers")
def add_worker(x:Worker):
    return ok(lambda d:(d.add_worker(x.name,x.role,x.contact,x.compensation_type,
                                     x.compensation_amount),{"ok":True})[1])
class WorkerData(BaseModel):
    name:str
    role:str=""
    contact:str=""
    compensation_type:str="mensual"
    compensation_amount:float=0
@app.put("/api/workers/{worker_id}")
def update_worker(worker_id:int,x:WorkerData):
    return ok(lambda d:(d.update_worker(worker_id,x.name,x.role,x.contact,x.compensation_type,
                                        x.compensation_amount),{"ok":True})[1])
class SalaryDeduction(BaseModel):
    worker_name:str
    amount:float
    reason:str
@app.get("/api/workers/{worker_name}/deductions")
def worker_deductions(worker_name:str): return ok(lambda d:d.get_worker_salary_deductions(worker_name))
@app.post("/api/workers/deductions")
def add_worker_deduction(x:SalaryDeduction):
    return ok(lambda d:(d.add_worker_salary_deduction(x.worker_name,x.amount,x.reason),{"ok":True})[1])
@app.post("/api/workers/deductions/{deduction_id}/authorize")
def authorize_worker_deduction(deduction_id:int,authorized:bool=True):
    return ok(lambda d:(d.authorize_worker_salary_deduction(deduction_id,authorized),{"ok":True})[1])

@app.get("/api/shift/active")
def active_shift(point_id:int): return ok(lambda d: detail(d,d.get_active_shift(point_id)['id']) if d.get_active_shift(point_id) else None)
@app.post("/api/shift/open")
def open_shift(x:ShiftOpen):
    return ok(lambda d:(d.start_shift(
        x.point_id,x.cashier,x.supervisor,x.fondo_cambio,x.opening_counts,
        x.foreign_currency_code or config.get("General","foreign_currency_code","USD"),
        x.exchange_rate_usd if x.exchange_rate_usd is not None else (
            x.exchange_rate if x.exchange_rate is not None else config.getfloat("General","exchange_rate_usd",1)
        ),
        x.exchange_rate_eur if x.exchange_rate_eur is not None else config.getfloat("General","exchange_rate_eur",1),
    ),{"ok":True})[1])
@app.get("/api/shift/{sid}")
def get_shift(sid:int): return ok(lambda d:detail(d,sid))
@app.put("/api/shift/item")
def update_item(x:ItemUpdate): return ok(lambda d:(d.update_item_counts(**x.model_dump()),{"ok":True})[1])
@app.post("/api/shift/expense")
def add_expense(x:Expense): return ok(lambda d:(d.add_shift_expense(**x.model_dump()),{"ok":True})[1])
@app.delete("/api/shift/expense/{eid}")
def del_expense(eid:int): return ok(lambda d:(d.delete_shift_expense(eid),{"ok":True})[1])
@app.post("/api/shift/cash")
def cash(x:Cash):
    return ok(lambda d:(d.save_shift_receipts(
        x.shift_id,{float(k):int(v) for k,v in x.counts.items()},
        x.transfer_total,x.foreign_currency_total,
    ) if not x.currency_totals else d.save_shift_receipts_multi(
        x.shift_id,{float(k):int(v) for k,v in x.counts.items()},
        x.transfer_total,x.currency_totals,
    ),{"ok":True})[1])
class ShiftPayments(BaseModel):
    shift_id:int
    transfer_total:float=0
    foreign_currency_total:float=0
@app.post("/api/shift/payments")
def shift_payments(x:ShiftPayments):
    return ok(lambda d:(d.save_shift_payments(x.shift_id,x.transfer_total,x.foreign_currency_total),{"ok":True})[1])
@app.post("/api/shift/{sid}/close")
def close_shift(sid:int): return ok(lambda d:d.close_shift(sid))
@app.post("/api/shift/{sid}/reopen")
def reopen_shift(sid:int): return ok(lambda d:(d.reopen_shift(sid),{"ok":True})[1])
@app.post("/api/shift/{sid}/recompute")
def recompute(sid:int): return ok(lambda d:d.recompute_closed_shift_totals(sid))

@app.get("/api/history")
def history(point_id:Optional[int]=None,text:str=""): return ok(lambda d:d.search_shifts(point_id,text))
@app.get("/api/products/expiring")
def expiring_products(date_to:str,point_id:Optional[int]=None):
    return ok(lambda d:d.get_expiring_products(date_to,point_id))
@app.get("/api/history/{sid}")
def history_detail(sid:int): return ok(lambda d:detail(d,sid))

@app.get("/api/balance")
def balance(date_from:str,date_to:str,point_id:Optional[int]=None):
    def f(d):
        s=d.get_shifts_in_range(date_from,date_to,point_id); ids=[x['id'] for x in s]
        return {"summary":d.summarize_shifts(s),"top":d.get_top_products_for_shift_ids(ids,10),"daily":d.get_daily_series_for_shift_ids(ids),"expenses":d.get_expenses_in_range(date_from,date_to,point_id)}
    return ok(f)
@app.get("/api/staff/summary")
def staff_summary(): return ok(lambda d:d.get_worker_summary())
@app.get("/api/staff/{name}")
def staff_history(name:str): return ok(lambda d:d.get_worker_shift_history(name))

@app.get("/api/config")
def get_config(): return {"nombre":config.get('Empresa','nombre',''),"direccion":config.get('Empresa','direccion',''),"telefono":config.get('Empresa','telefono',''),"moneda":config.get('General','moneda','$'),"foreign_currency_code":config.get('General','foreign_currency_code','USD'),"exchange_rate":config.getfloat('General','exchange_rate',1),"exchange_rate_usd":config.getfloat('General','exchange_rate_usd',1),"exchange_rate_eur":config.getfloat('General','exchange_rate_eur',1),"ia_enabled":config.ia_enabled,"ia_url":config.get('IA','url','http://127.0.0.1:8081'),"ia_modelo":config.get('IA','modelo',''),"ia_api_key_configured":bool(config.get('IA','api_key','').strip()),"stock_minimo":config.stock_minimo}
@app.put("/api/config")
def save_config(x:ConfigData):
    if x.exchange_rate is not None and x.exchange_rate <= 0:
        raise HTTPException(400,"El tipo de cambio debe ser mayor que cero.")
    for rate in (x.exchange_rate, x.exchange_rate_usd, x.exchange_rate_eur):
        if rate is not None and (not math.isfinite(rate) or rate <= 0):
            raise HTTPException(400,"Las tasas de USD y EUR deben ser mayores que cero.")
    if x.foreign_currency_code is not None and not 1 <= len(x.foreign_currency_code.strip()) <= 8:
        raise HTTPException(400,"El código de moneda debe tener entre 1 y 8 caracteres.")
    config.set('Empresa','nombre',x.nombre); config.set('Empresa','direccion',x.direccion); config.set('Empresa','telefono',x.telefono); config.set('General','moneda',x.moneda); config.set('Impresora','stock_minimo_alerta',x.stock_minimo); config.set('IA','url',x.ia_url); config.set('IA','modelo',x.ia_modelo)
    if x.foreign_currency_code is not None: config.set('General','foreign_currency_code',x.foreign_currency_code.strip().upper())
    if x.exchange_rate is not None:
        config.set('General','exchange_rate',x.exchange_rate)
    if x.exchange_rate_usd is not None:
        config.set('General','exchange_rate_usd',x.exchange_rate_usd)
        config.set('General','exchange_rate',x.exchange_rate_usd)
    if x.exchange_rate_eur is not None:
        config.set('General','exchange_rate_eur',x.exchange_rate_eur)
    if x.ia_enabled is not None: config.set('IA','enabled','true' if x.ia_enabled else 'false')
    if x.ia_clear_api_key:
        config.set('IA','api_key','')
    elif x.ia_api_key and x.ia_api_key.strip():
        config.set('IA','api_key',x.ia_api_key.strip())
    config.save(); return {"ok":True}

@app.get("/api/license")
def get_license():
    d=db()
    try:
        row = d.get_license()
        if not row:
            return {
                "licensed": False,
                "customer": "",
                "expires_on": "",
                "error": "No hay licencia activada.",
                "activation_id": device_activation_id(),
            }
        try:
            valid = validate_stored_license(row)
        except BusinessError as exc:
            return {
                "licensed": False,
                "customer": row["customer"],
                "expires_on": row["expires_on"],
                "error": str(exc),
                "activation_id": device_activation_id(),
            }
        return {
            "licensed": True,
            "customer": valid["customer"],
            "expires_on": valid["expires_on"],
            "error": "",
            "activation_id": device_activation_id(),
        }
    finally:
        d.close()
@app.get("/api/ia/test")
def ia_test():
    if not config.ia_enabled: raise HTTPException(404,"El apartado de IA está deshabilitado.")
    c=LlamaClient(config.get('IA','url','http://127.0.0.1:8081'), api_key=config.get('IA','api_key',''))
    try: return {"ok":True,"health":c.health(),"models":c.models()}
    except Exception as e: raise HTTPException(400,str(e))

_agents={}
_agent_locks={}
_agents_guard=threading.Lock()

def get_agent(conversation_id):
    key=(config.get('IA','url','http://127.0.0.1:8081'),config.get('IA','modelo',''),config.get('IA','api_key',''),conversation_id)
    with _agents_guard:
        if key not in _agents: _agents[key]=Agent(DB_PATH,key[0],key[1] or None,key[2])
        if key not in _agent_locks: _agent_locks[key]=threading.Lock()
        return _agents[key],_agent_locks[key]
class AIRequest(BaseModel):
    text:str
    point_id:Optional[int]=None
    view:str="dashboard"
    reset:bool=False
    conversation_id:str="default"

@app.post("/api/ia/chat")
def ai_chat(x:AIRequest):
    if not config.ia_enabled: raise HTTPException(404,"El apartado de IA está deshabilitado.")
    d=db()
    try:
        context={"vista":x.view,"point_id":x.point_id}
        if x.point_id:
            context["point"]=d.get_point(x.point_id); sh=d.get_active_shift(x.point_id)
            if sh: context["turno_activo"]={"id":sh['id'],"cashier":sh['cashier_name'],"supervisor":sh['supervisor_name'],"opened_at":sh['opened_at']}
    finally:d.close()
    agent,lock=get_agent(x.conversation_id)
    with lock:
        if x.reset: agent.reset()
        try: return {"ok":True,"answer":agent.ask(x.text,context=context)}
        except Exception as e: raise HTTPException(400,str(e))

# PDFs reuse existing reporting engine without changing the business layer.
@app.get("/api/report/shift/{sid}.pdf")
def shift_pdf(sid:int):
    from reports import generate_shift_pdf
    d=db()
    try:
        s=detail(d,sid); path=os.path.join(tempfile.gettempdir(),f"dg_shift_{sid}.pdf"); generate_shift_pdf(s,s['items'],s['expenses'],s['cash_counts'],s['totals'],path); return FileResponse(path,media_type='application/pdf',filename=f"cuadre_{sid}.pdf")
    finally:d.close()

@app.get("/api/report/balance.pdf")
def balance_pdf(date_from:str,date_to:str,point_id:Optional[int]=None):
    from reports import generate_balance_pdf
    d=db()
    try:
        shifts=d.get_shifts_in_range(date_from,date_to,point_id); ids=[s['id'] for s in shifts]; summary=d.summarize_shifts(shifts); top=d.get_top_products_for_shift_ids(ids,10); daily=d.get_daily_series_for_shift_ids(ids); workers=d.get_worker_summary(); label=d.get_point(point_id)['name'] if point_id and d.get_point(point_id) else 'Todos los puntos'; path=os.path.join(tempfile.gettempdir(),f"dg_balance_{date_from}_{date_to}.pdf"); generate_balance_pdf(date_from,date_to,label,summary,top,daily,workers,path); return FileResponse(path,media_type='application/pdf',filename=f"balance_{date_from}_{date_to}.pdf")
    finally:d.close()
