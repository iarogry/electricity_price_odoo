# -*- coding: utf-8 -*-
# Метадані модуля Odoo

{
    'name': "Ціни на Електроенергію РДН",
    'summary': """Модуль для збору даних про ціну електроенергії на ринку РДН з Transparency Platform.""",
    'description': """
        Цей модуль дозволяє автоматично та вручну завантажувати дані про ціну електроенергії
        з Transparency Platform Restful API (ENTSO-E) для різних країн.
        Дані зберігаються з унікальною ідентифікацією за роком, місяцем, днем та годиною.
    """,
    'author': "Ярослав Гришин", # Замініть на ваше ім'я
    'website': "http://www.hlibodar.com.ua", # Замініть на ваш вебсайт
    'category': 'Custom/Electricity',
    'version': '1.0',
    'depends': ['base', 'web'], # Залежності модуля
    'data': [
        'security/ir.model.access.csv',
         'views/entsoe_domain_views.xml', 
        'views/electricity_price_views.xml',  
        'wizards/import_price_wizard_views.xml', 
        'views/res_country_views.xml',
        'views/res_config_settings_views.xml',  
        'views/menus.xml',
        'data/ir_cron.xml',
    ],
    'images': ['static/description/icon.png'], # Додайте іконку модуля
    'license': 'LGPL-3',
    'installable': True,
    'application': True,
    'auto_install': False,
}
