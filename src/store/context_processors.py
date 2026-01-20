import json

def cart_context(request):
    try:
        # Retrieve the cart from the session
        cart = request.session.get('cart', {})
        
        # Check if the cart is valid JSON (log for debugging)
        print("Cart data:", cart)  # Log the cart data
        json.dumps(cart)  # Validate that cart is JSON serializable

        # Calculate cart length
        cart_length = len(cart) if cart else 0

        return {
            "cart_length": cart_length
        }

    except Exception as e:
        print("Context Processor Error:", e)
        return {
            "cart_length": 0  # Return a safe default if an error occurs
        }