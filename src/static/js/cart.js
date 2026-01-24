function getCSRFToken() {
    const name = 'csrftoken=';
    const cookies = document.cookie.split(';');

    for (let cookie of cookies) {
        cookie = cookie.trim();
        if (cookie.startsWith(name)) {
            return cookie.substring(name.length);
        }
    }
    return '';
}

// Add to cart
document.addEventListener("DOMContentLoaded", function () {
    const table = document.getElementById("product-table");
    if (table) {
        table.addEventListener("click", function (e) {
            if (e.target && e.target.classList.contains("add-btn")) {
                const row = e.target.closest("tr");
                let product_id = row.dataset.productId;
                let endPointUrl = row.dataset.endPointUrl;
                let item_quantity = row.querySelector(".item-quantity").value;
                let package_quantity = row.querySelector(".package-quantity").value;
                let package_price = row.querySelector(".package-price").value;
                let item_price = row.querySelector(".item-price").value;

                const data = {
                    product_id,
                    item_quantity,
                    package_quantity,
                    item_price,
                    package_price,
                };
                if (item_quantity || package_quantity) {
                    fetch(endPointUrl, {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/json",
                            "X-CSRFToken": getCSRFToken(),
                        },
                        body: JSON.stringify(data),
                    })
                        .then((res) => res.json())
                        .then((response) => {
                            const notification = document.querySelector(".sticky-notification");
                            if (notification) {
                                notification.classList.remove("hidden");
                                notification.classList.add("flex");
                                setTimeout(() => {
                                    notification.classList.add("hidden");
                                    notification.classList.remove("flex");
                                }, 2400);
                            }
                            document.getElementById("notification").innerText = response.cart_length;
                            console.log(`${response.cart_length} Product added`);
                            document.getElementById("cart_length").innerText = response.cart_length;
                        })
                        .catch((error) => {
                            row.classList.add("border-error");
                            console.log(`Server Error: ${error}`);
                            alert("Failed to Add the Product.");
                        });
                }
            }
        });
    }
});

// update cart
document.addEventListener("DOMContentLoaded", function () {
    const table =
        document.getElementById("product-car-table") ||
        document.getElementById("product-cart-table");
    if (table) {
        table.addEventListener("change", function(e) {
            const row = e.target.closest("tr");
            let product_id = row.dataset.productId;
            let endPointUrl = row.dataset.endPointUrl;
            let item_quantity = row.querySelector(".item-quantity").value;
            let package_quantity = row.querySelector(".package-quantity").value;
            let package_price = row.querySelector(".package-price").value;
            let item_price = row.querySelector(".item-price").value;
            
            const data = {
                product_id,
                item_quantity,
                package_quantity,
                item_price,
                package_price,
            }
            console.log(data)
            fetch(endPointUrl,
            {
                method: 'POST',
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCSRFToken(),
                },
                body: JSON.stringify(data) 
            }).then(res => res.json())
            .then(response =>{
                console.log(`${response.cart_length} Product added`);
                document.getElementById("cart_length").innerText = response.cart_length;
            }).catch(error =>{
                console.log(`Server Error: ${error}`);
                alert("Failed to Add the Product.");
            })
        
        });
    }
});
