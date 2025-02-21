from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, g
from pymongo import MongoClient
from flask_session import Session

import os
import hashlib
from cashier_console import CashierConsole
from bson import ObjectId
from datetime import datetime
from threading import Thread

from controllers.Stats.stats import stats_bp

from controllers.Staff.csdl_blueprint import csdl_bp
from controllers.Request.csdlRequest_blueprint import csdl_request_bp

from controllers.Request.cashierRequest_blueprint import cashier_request_bp
from controllers.Staff.cashier_blueprint import cashier_bp

from controllers.Request.MarketingRequest_blueprint import marketing_request_bp
from controllers.Staff.marketing_blueprint import marketing_bp

from controllers.Request.BusinessOfficeRequest import business_request_bp
from controllers.Staff.business_blueprint import business_bp

from controllers.Request.RegistrarRequest_blueprint import registrar_request_bp
from controllers.Staff.registrar_blueprint import registrar_bp