# Cointakip

Binance Futures verilerine karşı kripto para işlem pozisyonlarını analiz eden Flask tabanlı web uygulaması.

## Özellikler

- Pozisyon girişi: coin, alış fiyatı, hedef 1/2, stop, kaldıraç, açılış tarihi, miktar ($)
- Binance Futures API'den gerçek zamanlı 1 dakikalık mum verisi çekme
- Pozisyon sonucunu otomatik tespit etme (hedef 1, hedef 2, stop, açık)
- Kâr/Zarar hesabı: yüzde ve dolar cinsinden, kaldıraçlı
- Fiyat grafiği (Matplotlib, PNG olarak gömülü)
- Pozisyon kaydetme ve listeleme
- Açık/Kapalı pozisyon takibi
- Otomatik kapatma: hedef veya stop tetiklendiğinde pozisyon kendiliğinden kapanır
- Manuel kapatma: anlık Binance fiyatıyla veya girilen fiyatla

## Kurulum

```bash
pip install -r requirements.txt
```

## Çalıştırma

```bash
# Geliştirme (port 5000, debug mod)
python web_app.py

# Üretim
gunicorn web_app:app
```

## Kullanım

1. Coin sembolünü gir (örn. `BTCUSDT`)
2. Alış fiyatı, hedef(ler), stop ve kaldıraç değerlerini gir
3. İsteğe bağlı olarak işlem miktarını dolar cinsinden gir
4. Açılış tarih/saatini belirt (Türkiye saati)
5. **Kontrol Et** → Binance'tan veri çeker, sonucu ve grafiği gösterir
6. **Kaydet** → Pozisyonu sol panele kaydeder
7. Kaydedilen pozisyonlar üzerinden **✕** butonu ile manuel kapatma yapılabilir

## Veri Depolama

Veritabanı kullanılmaz; iki JSON dosyasıyla çalışır:

| Dosya | İçerik |
|---|---|
| `saved_positions.json` | Kaydedilen pozisyonlar (durum, K/Z, kapanış bilgisi dahil) |
| `web_settings.json` | Son kullanılan form değerleri (otomatik doldurma için) |

## Teknoloji

- **Backend:** Python 3, Flask 2.3+
- **Sunucu:** Gunicorn
- **Frontend:** Bootstrap 5.3.2, Jinja2, Vanilla JS
- **Grafik:** Matplotlib (sunucu tarafı PNG)
- **Veri:** Binance Futures REST API (`fapi.binance.com`)
- **Zaman dilimi:** Europe/Istanbul

## Bilinen Kısıtlamalar

- Binance API başına maksimum 1000 mum döndürür (~16.6 saat). Daha uzun pozisyonlarda veri eksik olabilir.
- JSON dosyalarına eş zamanlı yazma koruması yoktur.
- Pozisyon ID'leri silme sonrası yeniden eklemede çakışabilir.
