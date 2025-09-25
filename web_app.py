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
    # Add timestamp and unique ID
    position_data['saved_at'] = datetime.now(LOCAL_TZ).strftime('%Y-%m-%d %H:%M:%S')
    position_data['id'] = len(positions) + 1
    positions.append(position_data)
    return save_positions(positions)


def delete_position(position_id):
    positions = load_saved_positions()
    positions = [p for p in positions if p.get('id') != position_id]
    return save_positions(positions)


def get_binance_klines(symbol: str, start_time: datetime, end_time: datetime):
    url = 'https://api.binance.com/api/v3/klines'
    params = {
        'symbol': symbol,
        'interval': '1m',
        'startTime': int(start_time.timestamp() * 1000),
        'endTime': int(end_time.timestamp() * 1000),
        'limit': 1000,
    }
    # Debug prints (server console)
    print('[DEBUG] Binance Klines Request:')
    print(f"  URL: {url}")
    print(f"  Params: symbol={params['symbol']}, interval={params['interval']}, startTime={params['startTime']}, endTime={params['endTime']}, limit={params['limit']}")

    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    klines = resp.json()
    if not klines:
        raise RuntimeError('Veri bulunamadı')

    try:
        total = len(klines)
        print(f"[DEBUG] Binance Klines Response: {total} kayıt")
        preview_first = klines[:3]
        preview_last = klines[-3:] if total >= 3 else []
        def fmt(k):
            t = datetime.fromtimestamp(int(k[0]) / 1000, tz=timezone.utc).astimezone(LOCAL_TZ)
            return f"{t.strftime('%Y-%m-%d %H:%M:%S')} | O:{float(k[1]):.4f} H:{float(k[2]):.4f} L:{float(k[3]):.4f} C:{float(k[4]):.4f}"
        if preview_first:
            print('[DEBUG] İlk 3 kline:')
            for k in preview_first:
                print('  ', fmt(k))
        if preview_last:
            print('[DEBUG] Son 3 kline:')
            for k in preview_last:
                print('  ', fmt(k))
    except Exception as e:
        print('[DEBUG] Yanıt önizleme yazdırılırken hata:', e)

    return klines


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

    # Precedence: stop before any target → stop; else target2 > target1; else open
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


@app.route('/', methods=['GET', 'POST'])
def index():
    defaults = load_settings()
    saved_positions = load_saved_positions()
    
    # Check if loading from saved position
    load_position_id = request.args.get('load')
    if load_position_id:
        try:
            position_id = int(load_position_id)
            position = next((p for p in saved_positions if p.get('id') == position_id), None)
            if position:
                defaults = {
                    'coin': position.get('coin', ''),
                    'entry_price': str(position.get('entry_price', '')),
                    'target_price1': str(position.get('target_price1', '')),
                    'target_price2': str(position.get('target_price2', '')),
                    'stop_price': str(position.get('stop_price', '')),
                    'leverage': str(position.get('leverage', '')),
                    'open_date': position.get('open_date', ''),
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
        },
        'result': None,
        'chart_data_url': None,
        'live_status': None,
        'error': None,
        'success_message': None,
        'saved_positions': saved_positions,
    }

    if request.method == 'POST':
        action = request.form.get('action', 'check')
        
        try:
            coin = request.form.get('coin', '').strip().upper()
            entry_price = float(request.form.get('entry_price', '0'))
            target1 = float(request.form.get('target_price1', '0'))
            target2_str = request.form.get('target_price2', '').strip()
            target2 = float(target2_str) if target2_str else None
            stop_price = float(request.form.get('stop_price', '0'))
            leverage = float(request.form.get('leverage', '0'))
            open_date_str = request.form.get('open_date', '').strip()

            if not coin or entry_price <= 0 or target1 <= 0 or (target2 is not None and target2 <= 0) or stop_price <= 0 or leverage <= 0:
                raise ValueError('Lütfen tüm zorunlu alanları geçerli değerlerle doldurun.')

            if action == 'save':
                # Save position
                position_data = {
                    'coin': coin,
                    'entry_price': entry_price,
                    'target_price1': target1,
                    'target_price2': target2,
                    'stop_price': stop_price,
                    'leverage': leverage,
                    'open_date': open_date_str,
                    'name': f"{coin} - {datetime.now(LOCAL_TZ).strftime('%m/%d %H:%M')}"
                }
                
                if add_position(position_data):
                    context['success_message'] = f"{coin} pozisyonu başarıyla kaydedildi!"
                    # Reload saved positions
                    context['saved_positions'] = load_saved_positions()
                else:
                    context['error'] = "Pozisyon kaydetme sırasında bir hata oluştu."
            
            elif action == 'check':
                # Check position (existing logic)
                naive = datetime.strptime(open_date_str, '%Y-%m-%d %H:%M')
                open_date_local = LOCAL_TZ.localize(naive)
                open_date_utc = open_date_local.astimezone(timezone.utc)
                now_utc = datetime.now(LOCAL_TZ).astimezone(timezone.utc)

                klines = get_binance_klines(coin, open_date_utc, now_utc)
                position_type = determine_position_type(entry_price, target1)
                eval_res = evaluate_position(klines, entry_price, target1, target2, stop_price, leverage, position_type, LOCAL_TZ)

                # Live status (always)
                last_close = eval_res['last_close']
                live_pnl, live_status = calculate_profit_loss(entry_price, target1, stop_price, leverage, last_close, 'open', position_type)
                live_color = 'green' if live_pnl > 0 else ('red' if live_pnl < 0 else 'black')
                context['live_status'] = {
                    'text': f"Güncel: {live_status} %{'{:.2f}'.format(live_pnl)} | Fiyat: {'{:.2f}'.format(last_close)}",
                    'color': live_color,
                }

                # Outcome
                if eval_res['stop_hit'] and eval_res['stop_before_any_target']:
                    pnl, status = calculate_profit_loss(entry_price, target1, stop_price, leverage, eval_res['stop_hit_price'], 'stop', position_type)
                    context['result'] = {
                        'title': f"❌ {position_type.upper()} pozisyon {eval_res['stop_time'].strftime('%Y-%m-%d %H:%M')} tarihinde stop oldu ({status}).",
                        'detail': f"{status}: %{'{:.2f}'.format(pnl)} (Stop: {'{:.2f}'.format(stop_price)}, Ulaşılan: {'{:.2f}'.format(eval_res['stop_hit_price'])}, Kaldıraç: {int(leverage) if float(leverage).is_integer() else leverage}x)",
                        'color': 'red',
                    }
                elif eval_res['target2_hit']:
                    pnl, status = calculate_profit_loss(entry_price, target2, stop_price, leverage, eval_res['target2_price'], 'target', position_type)
                    context['result'] = {
                        'title': f"✅ {position_type.upper()} pozisyon {eval_res['target2_time'].strftime('%Y-%m-%d %H:%M')} tarihinde Hedef 2'ye ulaştı ({status}).",
                        'detail': f"{status}: %{'{:.2f}'.format(pnl)} (Hedef 2: {'{:.2f}'.format(target2)}, Ulaşılan: {'{:.2f}'.format(eval_res['target2_price'])}, Kaldıraç: {int(leverage) if float(leverage).is_integer() else leverage}x)",
                        'color': 'green',
                    }
                elif eval_res['target1_hit']:
                    pnl, status = calculate_profit_loss(entry_price, target1, stop_price, leverage, eval_res['target1_price'], 'target', position_type)
                    context['result'] = {
                        'title': f"✅ {position_type.upper()} pozisyon {eval_res['target1_time'].strftime('%Y-%m-%d %H:%M')} tarihinde Hedef 1'e ulaştı ({status}).",
                        'detail': f"{status}: %{'{:.2f}'.format(pnl)} (Hedef 1: {'{:.2f}'.format(target1)}, Ulaşılan: {'{:.2f}'.format(eval_res['target1_price'])}, Kaldıraç: {int(leverage) if float(leverage).is_integer() else leverage}x)",
                        'color': 'green',
                    }
                else:
                    pnl, status = calculate_profit_loss(entry_price, target1, stop_price, leverage, last_close, 'open', position_type)
                    if target2 is not None:
                        detail = f"{status}: %{'{:.2f}'.format(pnl)} (Hedef 1: {'{:.2f}'.format(target1)}, Hedef 2: {'{:.2f}'.format(target2)}, Stop: {'{:.2f}'.format(stop_price)}, Kaldıraç: {int(leverage) if float(leverage).is_integer() else leverage}x)"
                    else:
                        detail = f"{status}: %{'{:.2f}'.format(pnl)} (Hedef: {'{:.2f}'.format(target1)}, Stop: {'{:.2f}'.format(stop_price)}, Kaldıraç: {int(leverage) if float(leverage).is_integer() else leverage}x)"
                    context['result'] = {
                        'title': f"⏳ {position_type.upper()} pozisyon açık. Hedefe ulaşmadı. Şu anki fiyat: {'{:.2f}'.format(last_close)}",
                        'detail': detail,
                        'color': 'green' if pnl > 0 else ('red' if pnl < 0 else 'black'),
                    }

                # Chart
                context['chart_data_url'] = render_chart(klines, entry_price, target1, target2, stop_price, position_type)

            # Persist inputs for both check and save actions
            save_settings({
                'coin': coin,
                'entry_price': request.form.get('entry_price', ''),
                'target_price1': request.form.get('target_price1', ''),
                'target_price2': request.form.get('target_price2', ''),
                'stop_price': request.form.get('stop_price', ''),
                'leverage': request.form.get('leverage', ''),
                'open_date': request.form.get('open_date', ''),
            })

            # Reflect submitted values in the form
            context['form'] = {
                'coin': coin,
                'entry_price': request.form.get('entry_price', ''),
                'target_price1': request.form.get('target_price1', ''),
                'target_price2': request.form.get('target_price2', ''),
                'stop_price': request.form.get('stop_price', ''),
                'leverage': request.form.get('leverage', ''),
                'open_date': request.form.get('open_date', ''),
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


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
