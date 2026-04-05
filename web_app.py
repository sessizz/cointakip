import io
import json
import base64
from datetime import datetime, timezone

import requests
import pytz
from flask import Flask, render_template, request, redirect, url_for, jsonify

app = Flask(__name__)

LOCAL_TZ = pytz.timezone('Europe/Istanbul')
SETTINGS_PATH = 'web_settings.json'
SAVED_POSITIONS_PATH = 'saved_positions.json'

CLOSE_REASON_LABELS = {
    'kar': 'Kar Alındı',
    'stop_manuel': 'Manuel Stop',
    'stop_oto': 'Otomatik Stop',
    'hedef1_oto': 'Hedef 1 Otomatik',
    'hedef2_oto': 'Hedef 2 Otomatik',
    'diger': 'Diğer',
    'manuel': 'Manuel',
}


def trf(value, decimals=4):
    """Sayıyı Türkçe ondalık ayracıyla (virgül) formatlar."""
    try:
        return f"{float(value):.{decimals}f}".replace('.', ',')
    except (ValueError, TypeError):
        return str(value)


app.jinja_env.filters['trf'] = trf


def parse_float(s):
    """Virgül veya nokta ondalık ayracını kabul eder."""
    return float(str(s).strip().replace(',', '.'))


def load_settings():
    try:
        with open(SETTINGS_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except FileNotFoundError:
        return {}
    except Exception:
        return {}
    return {}


def save_settings(data):
    try:
        with open(SETTINGS_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_saved_positions():
    try:
        with open(SAVED_POSITIONS_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except FileNotFoundError:
        return []
    except Exception:
        return []
    return []


def save_positions(positions):
    try:
        with open(SAVED_POSITIONS_PATH, 'w', encoding='utf-8') as f:
            json.dump(positions, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def add_position(position_data):
    positions = load_saved_positions()
    position_data['saved_at'] = datetime.now(LOCAL_TZ).strftime('%Y-%m-%d %H:%M:%S')
    position_data['id'] = max((p.get('id', 0) for p in positions), default=0) + 1
    position_data.setdefault('status', 'open')
    position_data.setdefault('amount', 0)
    positions.append(position_data)
    return save_positions(positions)


def update_position(position_id, position_data):
    positions = load_saved_positions()
    for i, p in enumerate(positions):
        if p.get('id') == position_id:
            # Koru: id, saved_at, durum ve kapanış bilgileri
            position_data['id'] = p['id']
            position_data['saved_at'] = p.get('saved_at', datetime.now(LOCAL_TZ).strftime('%Y-%m-%d %H:%M:%S'))
            position_data['status'] = p.get('status', 'open')
            for key in ['close_price', 'close_time', 'close_reason', 'pnl_percent', 'pnl_dollar']:
                if key in p:
                    position_data[key] = p[key]
            positions[i] = position_data
            return save_positions(positions)
    return False

def delete_position(position_id):
    positions = load_saved_positions()
    positions = [p for p in positions if p.get('id') != position_id]
    return save_positions(positions)


def update_position_close(position_id, close_price, close_reason, pnl_percent, pnl_dollar):
    positions = load_saved_positions()
    for p in positions:
        if p.get('id') == position_id:
            p['status'] = 'closed'
            p['close_price'] = close_price
            p['close_time'] = datetime.now(LOCAL_TZ).strftime('%Y-%m-%d %H:%M:%S')
            p['close_reason'] = close_reason
            p['pnl_percent'] = round(pnl_percent, 2)
            p['pnl_dollar'] = round(pnl_dollar, 2) if pnl_dollar is not None else None
            break
    return save_positions(positions)


def get_current_price(symbol):
    url = 'https://fapi.binance.com/fapi/v1/ticker/price'
    resp = requests.get(url, params={'symbol': symbol}, timeout=10)
    resp.raise_for_status()
    return float(resp.json()['price'])


def get_binance_klines(symbol: str, start_time: datetime, end_time: datetime):
    url = 'https://fapi.binance.com/fapi/v1/klines'
    all_klines = []
    current_start = int(start_time.timestamp() * 1000)
    end_ms = int(end_time.timestamp() * 1000)
    page = 0

    while True:
        params = {
            'symbol': symbol,
            'interval': '1m',
            'startTime': current_start,
            'endTime': end_ms,
            'limit': 1000,
        }
        page += 1
        print(f'[DEBUG] Binance Klines Request (sayfa {page}): symbol={symbol}, startTime={current_start}, endTime={end_ms}')
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        klines = resp.json()
        if not klines:
            break
        all_klines.extend(klines)
        print(f'[DEBUG] Sayfa {page}: {len(klines)} kayıt (toplam: {len(all_klines)})')
        if len(klines) < 1000:
            break
        # Bir sonraki batch: son mumun açılış zamanı + 1 dakika
        current_start = int(klines[-1][0]) + 60000
        if current_start >= end_ms:
            break

    if not all_klines:
        raise RuntimeError('Veri bulunamadı')

    def fmt(k):
        t = datetime.fromtimestamp(int(k[0]) / 1000, tz=timezone.utc).astimezone(LOCAL_TZ)
        return f"{t.strftime('%Y-%m-%d %H:%M:%S')} | O:{float(k[1]):.4f} H:{float(k[2]):.4f} L:{float(k[3]):.4f} C:{float(k[4]):.4f}"
    print(f'[DEBUG] Toplam {len(all_klines)} kline çekildi.')
    print('[DEBUG] İlk 3 kline:')
    for k in all_klines[:3]:
        print('  ', fmt(k))
    print('[DEBUG] Son 3 kline:')
    for k in all_klines[-3:]:
        print('  ', fmt(k))

    return all_klines


def determine_position_type(entry_price: float, target1: float) -> str:
    return 'long' if target1 > entry_price else 'short'


def calculate_profit_loss(entry_price: float, target_price: float, stop_price: float, leverage: float, hit_price: float, hit_type: str, position_type: str):
    if hit_type == 'target':
        if position_type == 'long':
            price_change = ((target_price - entry_price) / entry_price) * 100
        else:
            price_change = ((entry_price - target_price) / entry_price) * 100
        leveraged_change = price_change * leverage
        return leveraged_change, 'Kâr'
    elif hit_type == 'stop':
        if position_type == 'long':
            price_change = ((stop_price - entry_price) / entry_price) * 100
        else:
            price_change = ((entry_price - stop_price) / entry_price) * 100
        leveraged_change = price_change * leverage
        return leveraged_change, 'Zarar'
    else:
        if position_type == 'long':
            price_change = ((hit_price - entry_price) / entry_price) * 100
        else:
            price_change = ((entry_price - hit_price) / entry_price) * 100
        leveraged_change = price_change * leverage
        status = 'Kâr' if leveraged_change > 0 else 'Zarar' if leveraged_change < 0 else 'Nötr'
        return leveraged_change, status


def evaluate_position(klines, entry_price, target1, target2, stop_price, leverage, position_type, local_tz):
    target1_hit = False
    target2_hit = False
    stop_hit = False
    target1_time = None
    target2_time = None
    stop_time = None
    target1_price = None
    target2_price = None
    stop_hit_price = None

    for k in klines:
        high = float(k[2])
        low = float(k[3])
        close = float(k[4])
        ktime = datetime.fromtimestamp(int(k[0]) / 1000, tz=timezone.utc)

        if position_type == 'long':
            if (not target1_hit) and high >= target1:
                target1_hit = True
                target1_price = min(high, target1)
                target1_time = ktime.astimezone(local_tz)
            if (target2 is not None) and (not target2_hit) and high >= target2:
                target2_hit = True
                target2_price = min(high, target2)
                target2_time = ktime.astimezone(local_tz)
            if (not stop_hit) and low <= stop_price:
                stop_hit = True
                stop_hit_price = max(low, stop_price)
                stop_time = ktime.astimezone(local_tz)
        else:
            if (not target1_hit) and low <= target1:
                target1_hit = True
                target1_price = max(low, target1)
                target1_time = ktime.astimezone(local_tz)
            if (target2 is not None) and (not target2_hit) and low <= target2:
                target2_hit = True
                target2_price = max(low, target2)
                target2_time = ktime.astimezone(local_tz)
            if (not stop_hit) and high >= stop_price:
                stop_hit = True
                stop_hit_price = min(high, stop_price)
                stop_time = ktime.astimezone(local_tz)

    stop_before_any_target = False
    if stop_hit:
        earliest_target_time = None
        if target1_hit:
            earliest_target_time = target1_time
        if target2_hit:
            if earliest_target_time is None or target2_time < earliest_target_time:
                earliest_target_time = target2_time
        if earliest_target_time is None or (stop_time <= earliest_target_time):
            stop_before_any_target = True

    result = {
        'target1_hit': target1_hit,
        'target2_hit': target2_hit,
        'stop_hit': stop_hit,
        'target1_time': target1_time,
        'target2_time': target2_time,
        'stop_time': stop_time,
        'target1_price': target1_price,
        'target2_price': target2_price,
        'stop_hit_price': stop_hit_price,
        'stop_before_any_target': stop_before_any_target,
        'last_close': float(klines[-1][4]) if klines else None,
    }
    return result


def render_chart(klines, entry_price, target1, target2, stop_price, position_type):
    from matplotlib.figure import Figure

    fig = Figure(figsize=(10, 3.5), dpi=100)
    ax = fig.add_subplot(111)

    if not klines:
        ax.set_title('Veri yok')
    else:
        times = []
        closes = []
        highs = []
        lows = []
        for k in klines:
            ktime = datetime.fromtimestamp(int(k[0]) / 1000, tz=timezone.utc).astimezone(LOCAL_TZ)
            times.append(ktime)
            highs.append(float(k[2]))
            lows.append(float(k[3]))
            closes.append(float(k[4]))
        ax.plot(times, closes, 'b-', linewidth=2, label='Kapanış')
        ax.plot(times, highs, 'g--', alpha=0.5, label='Yüksek')
        ax.plot(times, lows, 'r--', alpha=0.5, label='Düşük')
        ax.axhline(y=entry_price, color='orange', linestyle='-', linewidth=2, label=f'Alış: {entry_price:.2f}')
        ax.axhline(y=target1, color='green', linestyle='--', linewidth=2, label=f'Hedef 1: {target1:.2f}')
        if target2 is not None:
            ax.axhline(y=target2, color='teal', linestyle='--', linewidth=2, label=f'Hedef 2: {target2:.2f}')
        ax.axhline(y=stop_price, color='red', linestyle='--', linewidth=2, label=f'Stop: {stop_price:.2f}')
        ax.set_title(f'{position_type.upper()} Pozisyon - Fiyat Grafiği')
        ax.set_xlabel('Zaman (Türkiye)')
        ax.set_ylabel('Fiyat (USDT)')
        ax.legend(loc='upper left', fontsize=8)
        ax.grid(True, alpha=0.3)
        fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format='png')
    buf.seek(0)
    encoded = base64.b64encode(buf.read()).decode('ascii')
    buf.close()
    return f'data:image/png;base64,{encoded}'


def _dollar_str(amount, pnl_percent):
    """Return dollar P/L string if amount is set, else empty string."""
    if not amount:
        return ''
    pnl_dollar = amount * (pnl_percent / 100)
    sign = '+' if pnl_dollar >= 0 else ''
    return f' | {sign}${trf(pnl_dollar, 2)}'


@app.route('/', methods=['GET', 'POST'])
def index():
    defaults = load_settings()
    saved_positions = load_saved_positions()

    loaded_position_id = None
    load_position_id = request.args.get('load')
    if load_position_id:
        try:
            position_id = int(load_position_id)
            position = next((p for p in saved_positions if p.get('id') == position_id), None)
            if position:
                loaded_position_id = position_id
                defaults = {
                    'coin': position.get('coin', ''),
                    'entry_price': str(position.get('entry_price', '')),
                    'target_price1': str(position.get('target_price1', '')),
                    'target_price2': str(position.get('target_price2', '') or ''),
                    'stop_price': str(position.get('stop_price', '')),
                    'leverage': str(position.get('leverage', '')),
                    'open_date': position.get('open_date', ''),
                    'amount': str(position.get('amount', '') or ''),
                }
        except (ValueError, TypeError):
            pass

    context = {
        'form': {
            'coin': defaults.get('coin', 'BTCUSDT'),
            'entry_price': defaults.get('entry_price', '50000'),
            'target_price1': defaults.get('target_price1', '55000'),
            'target_price2': defaults.get('target_price2', ''),
            'stop_price': defaults.get('stop_price', '48000'),
            'leverage': defaults.get('leverage', '10'),
            'open_date': defaults.get('open_date', datetime.now(LOCAL_TZ).strftime('%Y-%m-%d %H:%M')),
            'amount': defaults.get('amount', ''),
            'position_id': loaded_position_id or '',
        },
        'result': None,
        'chart_data_url': None,
        'live_status': None,
        'error': None,
        'success_message': None,
        'saved_positions': saved_positions,
        'close_reason_labels': CLOSE_REASON_LABELS,
    }

    if request.method == 'POST':
        action = request.form.get('action', 'check')

        try:
            coin = request.form.get('coin', '').strip().upper()
            entry_price = parse_float(request.form.get('entry_price', '0'))
            target1 = parse_float(request.form.get('target_price1', '0'))
            target2_str = request.form.get('target_price2', '').strip()
            target2 = parse_float(target2_str) if target2_str else None
            stop_price = parse_float(request.form.get('stop_price', '0'))
            leverage = parse_float(request.form.get('leverage', '0'))
            open_date_str = request.form.get('open_date', '').strip()
            amount_str = request.form.get('amount', '').strip()
            amount = parse_float(amount_str) if amount_str else 0.0
            position_id_str = request.form.get('position_id', '').strip()
            position_id_for_update = int(position_id_str) if position_id_str else None

            if not coin or entry_price <= 0 or target1 <= 0 or (target2 is not None and target2 <= 0) or stop_price <= 0 or leverage <= 0:
                raise ValueError('Lütfen tüm zorunlu alanları geçerli değerlerle doldurun.')

            lev_str = f"{int(leverage) if float(leverage).is_integer() else leverage}x"

            if action == 'save':
                position_data = {
                    'coin': coin,
                    'entry_price': entry_price,
                    'target_price1': target1,
                    'target_price2': target2,
                    'stop_price': stop_price,
                    'leverage': leverage,
                    'open_date': open_date_str,
                    'amount': amount,
                    'name': f"{coin} - {datetime.now(LOCAL_TZ).strftime('%m/%d %H:%M')}"
                }

                if position_id_for_update:
                    if update_position(position_id_for_update, position_data):
                        context['success_message'] = f"{coin} pozisyonu güncellendi!"
                        context['saved_positions'] = load_saved_positions()
                    else:
                        context['error'] = "Pozisyon güncellenirken bir hata oluştu."
                else:
                    if add_position(position_data):
                        context['success_message'] = f"{coin} pozisyonu kaydedildi!"
                        context['saved_positions'] = load_saved_positions()
                    else:
                        context['error'] = "Pozisyon kaydedilirken bir hata oluştu."

            elif action == 'check':
                naive = datetime.strptime(open_date_str, '%Y-%m-%d %H:%M')
                open_date_local = LOCAL_TZ.localize(naive)
                open_date_utc = open_date_local.astimezone(timezone.utc)
                now_utc = datetime.now(LOCAL_TZ).astimezone(timezone.utc)

                klines = get_binance_klines(coin, open_date_utc, now_utc)
                position_type = determine_position_type(entry_price, target1)
                eval_res = evaluate_position(klines, entry_price, target1, target2, stop_price, leverage, position_type, LOCAL_TZ)

                last_close = eval_res['last_close']
                current_price = get_current_price(coin)
                live_pnl, live_status_text = calculate_profit_loss(entry_price, target1, stop_price, leverage, current_price, 'open', position_type)
                live_color = 'green' if live_pnl > 0 else ('red' if live_pnl < 0 else 'black')

                live_dollar = _dollar_str(amount, live_pnl)
                context['live_status'] = {
                    'text': f"Güncel: {live_status_text} %{trf(live_pnl, 2)}{live_dollar} | Fiyat: {trf(current_price, 2)}",
                    'color': live_color,
                }

                # Determine outcome
                auto_close_price = None
                auto_close_reason = None

                if eval_res['stop_hit'] and eval_res['stop_before_any_target']:
                    pnl, status = calculate_profit_loss(entry_price, target1, stop_price, leverage, eval_res['stop_hit_price'], 'stop', position_type)
                    dollar = _dollar_str(amount, pnl)
                    context['result'] = {
                        'title': f"❌ {position_type.upper()} pozisyon {eval_res['stop_time'].strftime('%Y-%m-%d %H:%M')} tarihinde stop oldu ({status}).",
                        'detail': f"{status}: %{trf(pnl, 2)}{dollar} (Stop: {trf(stop_price)}, Ulaşılan: {trf(eval_res['stop_hit_price'])}, Kaldıraç: {lev_str})",
                        'color': 'red',
                    }
                    auto_close_price = eval_res['stop_hit_price']
                    auto_close_reason = 'stop_oto'
                    auto_close_pnl = pnl

                elif eval_res['target2_hit']:
                    pnl, status = calculate_profit_loss(entry_price, target2, stop_price, leverage, eval_res['target2_price'], 'target', position_type)
                    dollar = _dollar_str(amount, pnl)
                    context['result'] = {
                        'title': f"✅ {position_type.upper()} pozisyon {eval_res['target2_time'].strftime('%Y-%m-%d %H:%M')} tarihinde Hedef 2'ye ulaştı ({status}).",
                        'detail': f"{status}: %{trf(pnl, 2)}{dollar} (Hedef 2: {trf(target2)}, Ulaşılan: {trf(eval_res['target2_price'])}, Kaldıraç: {lev_str})",
                        'color': 'green',
                    }
                    auto_close_price = eval_res['target2_price']
                    auto_close_reason = 'hedef2_oto'
                    auto_close_pnl = pnl

                elif eval_res['target1_hit']:
                    pnl, status = calculate_profit_loss(entry_price, target1, stop_price, leverage, eval_res['target1_price'], 'target', position_type)
                    dollar = _dollar_str(amount, pnl)
                    context['result'] = {
                        'title': f"✅ {position_type.upper()} pozisyon {eval_res['target1_time'].strftime('%Y-%m-%d %H:%M')} tarihinde Hedef 1'e ulaştı ({status}).",
                        'detail': f"{status}: %{trf(pnl, 2)}{dollar} (Hedef 1: {trf(target1)}, Ulaşılan: {trf(eval_res['target1_price'])}, Kaldıraç: {lev_str})",
                        'color': 'green',
                    }
                    auto_close_price = eval_res['target1_price']
                    auto_close_reason = 'hedef1_oto'
                    auto_close_pnl = pnl

                else:
                    pnl, status = calculate_profit_loss(entry_price, target1, stop_price, leverage, last_close, 'open', position_type)
                    dollar = _dollar_str(amount, pnl)
                    if target2 is not None:
                        detail = f"{status}: %{trf(pnl, 2)}{dollar} (Hedef 1: {trf(target1)}, Hedef 2: {trf(target2)}, Stop: {trf(stop_price)}, Kaldıraç: {lev_str})"
                    else:
                        detail = f"{status}: %{trf(pnl, 2)}{dollar} (Hedef: {trf(target1)}, Stop: {trf(stop_price)}, Kaldıraç: {lev_str})"
                    context['result'] = {
                        'title': f"⏳ {position_type.upper()} pozisyon açık. Hedefe ulaşmadı. Şu anki fiyat: {trf(current_price, 2)}",
                        'detail': detail,
                        'color': 'green' if pnl > 0 else ('red' if pnl < 0 else 'black'),
                    }

                # Auto-close saved position if stop/target was hit
                if position_id_for_update and auto_close_price is not None:
                    all_positions = load_saved_positions()
                    pos = next((p for p in all_positions if p.get('id') == position_id_for_update), None)
                    if pos and pos.get('status', 'open') == 'open':
                        pnl_dollar = amount * (auto_close_pnl / 100) if amount else None
                        update_position_close(position_id_for_update, auto_close_price, auto_close_reason, auto_close_pnl, pnl_dollar)
                        context['saved_positions'] = load_saved_positions()

                context['chart_data_url'] = render_chart(klines, entry_price, target1, target2, stop_price, position_type)

            # Persist form values
            save_settings({
                'coin': coin,
                'entry_price': request.form.get('entry_price', ''),
                'target_price1': request.form.get('target_price1', ''),
                'target_price2': request.form.get('target_price2', ''),
                'stop_price': request.form.get('stop_price', ''),
                'leverage': request.form.get('leverage', ''),
                'open_date': request.form.get('open_date', ''),
                'amount': request.form.get('amount', ''),
            })

            context['form'] = {
                'coin': coin,
                'entry_price': request.form.get('entry_price', ''),
                'target_price1': request.form.get('target_price1', ''),
                'target_price2': request.form.get('target_price2', ''),
                'stop_price': request.form.get('stop_price', ''),
                'leverage': request.form.get('leverage', ''),
                'open_date': request.form.get('open_date', ''),
                'amount': request.form.get('amount', ''),
                'position_id': position_id_for_update or '',
            }

        except Exception as e:
            context['error'] = str(e)

    return render_template('index.html', **context)


@app.route('/delete_position/<int:position_id>', methods=['POST'])
def delete_position_route(position_id):
    if delete_position(position_id):
        return redirect(url_for('index'))
    else:
        return redirect(url_for('index') + '?error=delete_failed')


@app.route('/close_position/<int:position_id>', methods=['POST'])
def close_position_route(position_id):
    positions = load_saved_positions()
    position = next((p for p in positions if p.get('id') == position_id), None)
    if not position:
        return redirect(url_for('index'))

    close_price_str = request.form.get('close_price', '').strip()
    close_reason = request.form.get('close_reason', 'manuel')

    try:
        if close_price_str:
            close_price = float(close_price_str)
        else:
            close_price = get_current_price(position['coin'])

        entry_price = float(position['entry_price'])
        target1 = float(position['target_price1'])
        stop_price = float(position['stop_price'])
        leverage = float(position['leverage'])
        amount = float(position.get('amount') or 0)
        position_type = determine_position_type(entry_price, target1)

        pnl_percent, _ = calculate_profit_loss(entry_price, target1, stop_price, leverage, close_price, 'open', position_type)
        pnl_dollar = amount * (pnl_percent / 100) if amount else None

        update_position_close(position_id, close_price, close_reason, pnl_percent, pnl_dollar)
    except Exception as e:
        print(f'[ERROR] close_position_route: {e}')

    return redirect(url_for('index'))


@app.route('/refresh_all', methods=['POST'])
def refresh_all():
    positions = load_saved_positions()
    for position in positions:
        if position.get('status', 'open') != 'open':
            continue
        try:
            coin = position['coin']
            entry_price = float(position['entry_price'])
            target1 = float(position['target_price1'])
            target2_val = position.get('target_price2')
            target2 = float(target2_val) if target2_val else None
            stop_price = float(position['stop_price'])
            leverage = float(position['leverage'])
            amount = float(position.get('amount') or 0)
            open_date_str = position['open_date']

            naive = datetime.strptime(open_date_str, '%Y-%m-%d %H:%M')
            open_date_local = LOCAL_TZ.localize(naive)
            open_date_utc = open_date_local.astimezone(timezone.utc)
            now_utc = datetime.now(LOCAL_TZ).astimezone(timezone.utc)

            klines = get_binance_klines(coin, open_date_utc, now_utc)
            position_type = determine_position_type(entry_price, target1)
            eval_res = evaluate_position(klines, entry_price, target1, target2, stop_price, leverage, position_type, LOCAL_TZ)

            auto_close_price = None
            auto_close_reason = None
            auto_close_pnl = None

            if eval_res['stop_hit'] and eval_res['stop_before_any_target']:
                auto_close_price = eval_res['stop_hit_price']
                auto_close_reason = 'stop_oto'
                auto_close_pnl, _ = calculate_profit_loss(entry_price, target1, stop_price, leverage, auto_close_price, 'stop', position_type)
            elif eval_res['target2_hit']:
                auto_close_price = eval_res['target2_price']
                auto_close_reason = 'hedef2_oto'
                auto_close_pnl, _ = calculate_profit_loss(entry_price, target2, stop_price, leverage, auto_close_price, 'target', position_type)
            elif eval_res['target1_hit']:
                auto_close_price = eval_res['target1_price']
                auto_close_reason = 'hedef1_oto'
                auto_close_pnl, _ = calculate_profit_loss(entry_price, target1, stop_price, leverage, auto_close_price, 'target', position_type)

            if auto_close_price is not None:
                pnl_dollar = amount * (auto_close_pnl / 100) if amount else None
                update_position_close(position['id'], auto_close_price, auto_close_reason, auto_close_pnl, pnl_dollar)

        except Exception as e:
            print(f"[ERROR] refresh_all {position.get('coin')}: {e}")

    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
