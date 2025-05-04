from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_user, logout_user, login_required, current_user
from urllib.parse import urlparse  # Changed from werkzeug.urls
from app import db
from app.models import User, Product, CartItem, Order, OrderItem
import stripe
from datetime import datetime

main = Blueprint('main', __name__)

@main.route('/')
@main.route('/home')
def home():
    products = Product.query.all()
    return render_template('home.html', products=products)

@main.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'danger')
            return redirect(url_for('main.register'))
        user = User(email=email, first_name=first_name, last_name=last_name)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('main.login'))
    return render_template('register.html')

@main.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user)
            next_page = request.args.get('next')
            if not next_page or urlparse(next_page).netloc != '':
                next_page = url_for('main.home')
            flash('Login successful!', 'success')
            return redirect(next_page)
        flash('Invalid email or password.', 'danger')
    return render_template('login.html')

@main.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('main.home'))

@main.route('/product/<int:product_id>')
def product(product_id):
    product = Product.query.get_or_404(product_id)
    return render_template('product.html', product=product)

@main.route('/cart')
@login_required
def cart():
    cart_items = CartItem.query.filter_by(user_id=current_user.id).all()
    total = sum(item.product.price * item.quantity for item in cart_items)
    return render_template('cart.html', cart_items=cart_items, total=total)

@main.route('/cart/add/<int:product_id>', methods=['POST'])
@login_required
def add_to_cart(product_id):
    product = Product.query.get_or_404(product_id)
    if product.stock <= 0:
        flash('Product is out of stock.', 'danger')
        return redirect(url_for('main.product', product_id=product_id))
    quantity = int(request.form.get('quantity', 1))
    if quantity > product.stock:
        flash(f'Only {product.stock} items in stock.', 'danger')
        return redirect(url_for('main.product', product_id=product_id))
    cart_item = CartItem.query.filter_by(user_id=current_user.id, product_id=product_id).first()
    if cart_item:
        cart_item.quantity += quantity
    else:
        cart_item = CartItem(user_id=current_user.id, product_id=product_id, quantity=quantity)
        db.session.add(cart_item)
    db.session.commit()
    flash('Product added to cart.', 'success')
    return redirect(url_for('main.cart'))

@main.route('/cart/remove/<int:cart_item_id>')
@login_required
def remove_from_cart(cart_item_id):
    cart_item = CartItem.query.get_or_404(cart_item_id)
    if cart_item.user_id != current_user.id:
        flash('Unauthorized action.', 'danger')
        return redirect(url_for('main.cart'))
    db.session.delete(cart_item)
    db.session.commit()
    flash('Product removed from cart.', 'success')
    return redirect(url_for('main.cart'))

@main.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    cart_items = CartItem.query.filter_by(user_id=current_user.id).all()
    if not cart_items:
        flash('Your cart is empty.', 'danger')
        return redirect(url_for('main.cart'))
    total = sum(item.product.price * item.quantity for item in cart_items)
    if request.method == 'POST':
        shipping_address = request.form.get('shipping_address')
        stripe_token = request.form.get('stripeToken')
        try:
            # Create Stripe charge
            stripe.api_key = current_app.config['STRIPE_SECRET_KEY']
            charge = stripe.Charge.create(
                amount=int(total * 100),  # Convert to cents
                currency='usd',
                source=stripe_token,
                description=f'Order for {current_user.email}'
            )
            # Create order
            order = Order(
                user_id=current_user.id,
                total_amount=total,
                status='completed',
                shipping_address=shipping_address,
                created_at=datetime.utcnow()
            )
            db.session.add(order)
            # Move cart items to order items
            for item in cart_items:
                order_item = OrderItem(
                    order=order,
                    product_id=item.product_id,
                    quantity=item.quantity,
                    unit_price=item.product.price
                )
                item.product.stock -= item.quantity
                db.session.add(order_item)
                db.session.delete(item)
            db.session.commit()
            flash('Order placed successfully!', 'success')
            return redirect(url_for('main.orders'))
        except stripe.error.StripeError as e:
            flash(f'Payment failed: {str(e)}', 'danger')
            return redirect(url_for('main.checkout'))
    return render_template('checkout.html', total=total, stripe_key=current_app.config['STRIPE_PUBLISHABLE_KEY'])

@main.route('/orders')
@login_required
def orders():
    orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.created_at.desc()).all()
    return render_template('orders.html', orders=orders)

@main.route('/admin', methods=['GET', 'POST'])
@login_required
def admin():
    if not current_user.is_admin:
        flash('Admin access required.', 'danger')
        return redirect(url_for('main.home'))
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        price = float(request.form.get('price'))
        stock = int(request.form.get('stock'))
        image_url = request.form.get('image_url')
        product = Product(name=name, description=description, price=price, stock=stock, image_url=image_url)
        db.session.add(product)
        db.session.commit()
        flash('Product added successfully.', 'success')
        return redirect(url_for('main.admin'))
    products = Product.query.all()
    return render_template('admin.html', products=products)

@main.route('/admin/edit/<int:product_id>', methods=['GET', 'POST'])
@login_required
def edit_product(product_id):
    if not current_user.is_admin:
        flash('Admin access required.', 'danger')
        return redirect(url_for('main.home'))
    product = Product.query.get_or_404(product_id)
    if request.method == 'POST':
        product.name = request.form.get('name')
        product.description = request.form.get('description')
        product.price = float(request.form.get('price'))
        product.stock = int(request.form.get('stock'))
        product.image_url = request.form.get('image_url')
        db.session.commit()
        flash('Product updated successfully.', 'success')
        return redirect(url_for('main.admin'))
    return render_template('admin.html', product=product, products=Product.query.all())

@main.route('/admin/delete/<int:product_id>')
@login_required
def delete_product(product_id):
    if not current_user.is_admin:
        flash('Admin access required.', 'danger')
        return redirect(url_for('main.home'))
    product = Product.query.get_or_404(product_id)
    db.session.delete(product)
    db.session.commit()
    flash('Product deleted successfully.', 'success')
    return redirect(url_for('main.admin'))