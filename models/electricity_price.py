# -*- coding: utf-8 -*-
# Модель для зберігання цін на електроенергію та логіка API-інтеграції

from odoo import fields, models, api, _
from odoo.exceptions import UserError
from datetime import datetime, timedelta
import requests
import xml.etree.ElementTree as ET
import logging

_logger = logging.getLogger(__name__)

class ElectricityPriceRdn(models.Model):
    _name = 'electricity.price.rdn'
    _description = 'Ціна Електроенергії РДН'
    _order = 'price_date desc, hour asc'

    country_id = fields.Many2one('res.country', string='Країна', required=True, help="Країна, для якої завантажено ціну")
    
    # Змінено з related на обчислюване поле (computed field)
    entsoe_domain_id = fields.Many2one(
        'electricity.entsoe.domain',
        string='Домен ENTSO-E',
        compute='_compute_entsoe_domain_id', # Вказуємо метод для обчислення
        store=True, # Зберігати обчислене значення в базі даних
        readonly=True, # Поле буде тільки для читання
        help="Домен ENTSO-E, що обчислюється на основі обраної країни."
    )
    
    price_date = fields.Date(string='Дата', required=True, help="Дата, до якої відноситься ціна")
    hour = fields.Integer(string='Година', required=True, help="Година (0-23) за місцевим часом домену")
    price = fields.Float(string='Ціна (EUR/MWh)', required=True, digits=(10, 4), help="Ціна електроенергії за мегават-годину")
    api_response_raw = fields.Text(string='Сира відповідь API', readonly=True, help="Сира XML-відповідь від API для перевірки")

    _sql_constraints = [
        ('unique_price_per_hour', 'unique(country_id, price_date, hour)', 'Ціна для цієї країни, дати та години вже існує!'),
    ]

    # Метод для обчислення значення entsoe_domain_id
    @api.depends('country_id') # Цей метод буде викликатися при зміні country_id
    def _compute_entsoe_domain_id(self):
        for record in self:
            if record.country_id and record.country_id.entsoe_domain_id:
                record.entsoe_domain_id = record.country_id.entsoe_domain_id
            else:
                record.entsoe_domain_id = False

    @api.model
    def _cron_fetch_daily_prices(self):
        """
        Планова дія: Завантажує ціни на електроенергію для наступного дня для всіх активних доменів.
        Запускається щодня після 14:00 (за часом сервера Odoo).
        """
        _logger.info("Запуск планової дії для завантаження щоденних цін на електроенергію.")
        today = fields.Date.today()
        # Завантажуємо дані на наступний день
        target_date = today + timedelta(days=1)
        
        entsoe_domains = self.env['electricity.entsoe.domain'].search([])
        if not entsoe_domains:
            _logger.warning("Не знайдено жодного налаштованого домену ENTSO-E. Будь ласка, налаштуйте їх у розділі 'Налаштування модуля'.")
            return

        for domain in entsoe_domains:
            _logger.info(f"Завантаження цін для домену: {domain.name} ({domain.domain_code}) на дату: {target_date}")
            try:
                self._fetch_and_store_prices(domain.country_id.id, target_date)
                self.env.cr.commit() # Фіксуємо зміни для кожного домену
            except Exception as e:
                _logger.error(f"Помилка при завантаженні цін для домену {domain.name} на дату {target_date}: {e}")
                self.env.cr.rollback() # Відкочуємо зміни у разі помилки

    @api.model
    def _fetch_and_store_prices(self, country_id, target_date):
        """
        Виконує запит до ENTSO-E API та зберігає отримані ціни.
        :param country_id: ID країни Odoo.
        :param target_date: Дата, для якої потрібно завантажити дані.
        """
        config = self.env['res.config.settings']._get_config_settings()
        api_base_url = config.get('entsoe_api_base_url')
        api_token = config.get('entsoe_api_token')

        if not api_base_url or not api_token:
            raise UserError(_("Будь ласка, налаштуйте 'Базовий URL API ENTSO-E' та 'Токен безпеки API ENTSO-E' у розділі Налаштувань модуля."))

        country = self.env['res.country'].browse(country_id)
        if not country.entsoe_domain_id:
            raise UserError(_(f"Для країни '{country.name}' не налаштовано домен ENTSO-E. Будь ласка, налаштуйте його."))

        domain_code = country.entsoe_domain_id.domain_code

        # Форматування дат для API (YYYYMMDDHHMM)
        start_period = target_date.strftime('%Y%m%d') + '0000'
        end_period = (target_date + timedelta(days=1)).strftime('%Y%m%d') + '0000'

        params = {
            'documentType': 'A44', # Price Document
            'in_Domain': domain_code,
            'out_Domain': domain_code,
            'periodStart': start_period,
            'periodEnd': end_period,
            'businessType': 'A04', # Day Ahead Prices
            'processType': 'A01', # Day Ahead
            'securityToken': api_token,
        }

        try:
            _logger.info(f"Виконання API-запиту: {api_base_url} з параметрами: {params}")
            response = requests.get(api_base_url, params=params, timeout=30)
            response.raise_for_status() # Викличе HTTPError для поганих відповідей (4xx або 5xx)
            raw_xml = response.text
            _logger.debug(f"Отримана XML-відповідь: {raw_xml}")

            root = ET.fromstring(raw_xml)
            # Використовуємо простір імен XML для коректного парсингу
            # Простір імен може змінюватися, тому краще його визначити динамічно або перевірити в XML
            # Зазвичай це "{urn:iec62325.351:tc57wg16:451:1:GenerationTimeSeries}" або подібний
            namespace = '{urn:iec62325.351:tc57wg16:451:1:GenerationTimeSeries}' # Це може бути іншим для цін, перевірте XML
            
            # Спробуємо знайти простір імен, якщо він є
            if '}' in root.tag:
                namespace = root.tag.split('}')[0] + '}'
            else:
                namespace = '' # Якщо простір імен не вказано

            prices_data = []
            for time_series in root.findall(f'.//{namespace}TimeSeries'):
                for period in time_series.findall(f'.//{namespace}Period'):
                    start_time_str = period.find(f'{namespace}timeInterval/{namespace}start').text
                    # Розбір дати та часу початку періоду
                    # Формат: YYYY-MM-DDTHH:MMZ (ISO 8601 UTC)
                    period_start_dt = datetime.strptime(start_time_str, '%Y-%m-%dT%H:%MZ')

                    for point in period.findall(f'.//{namespace}Point'):
                        position = int(point.find(f'{namespace}position').text)
                        price_amount = float(point.find(f'{namespace}price.amount').text)

                        # Година розраховується відносно початку періоду та позиції
                        # Позиція 1 відповідає першій годині періоду (00:00-01:00)
                        # ENTSO-E API зазвичай повертає дані за UTC.
                        # Якщо потрібен місцевий час, потрібно додати логіку конвертації часових поясів.
                        # Для спрощення, зберігаємо годину як позицію (0-23)
                        
                        # Перевірка, чи ціна вже існує для уникнення дублікатів
                        existing_price = self.search([
                            ('country_id', '=', country.id),
                            ('price_date', '=', target_date),
                            ('hour', '=', position - 1) # Позиція 1 = 0 година, Позиція 24 = 23 година
                        ], limit=1)

                        if not existing_price:
                            prices_data.append({
                                'country_id': country.id,
                                'price_date': target_date,
                                'hour': position - 1, # Переводимо позицію (1-24) у годину (0-23)
                                'price': price_amount,
                                'api_response_raw': raw_xml,
                            })
                        else:
                            _logger.info(f"Ціна для {country.name} на {target_date} годину {position - 1} вже існує. Пропущено.")

            if prices_data:
                self.create(prices_data)
                _logger.info(f"Успішно завантажено та збережено {len(prices_data)} цінових записів для {country.name} на {target_date}.")
            else:
                _logger.warning(f"Не знайдено цінових даних у відповіді API для {country.name} на {target_date}. Можливо, дані ще не доступні або запит некоректний.")

        except requests.exceptions.RequestException as e:
            _logger.error(f"Помилка запиту до API ENTSO-E: {e}")
            raise UserError(_(f"Помилка підключення до API ENTSO-E: {e}"))
        except ET.ParseError as e:
            _logger.error(f"Помилка парсингу XML-відповіді: {e}")
            raise UserError(_(f"Помилка парсингу відповіді від API ENTSO-E: {e}"))
        except Exception as e:
            _logger.error(f"Невідома помилка при обробці цін: {e}")
            raise UserError(_(f"Виникла невідома помилка: {e}"))
