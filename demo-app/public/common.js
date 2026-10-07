// Shared by every page of the DEMO shop. Cart lives in localStorage.
const cart = { get: () => JSON.parse(localStorage.getItem("cart") || "[]"), set: (c) => localStorage.setItem("cart", JSON.stringify(c)) };
document.addEventListener("DOMContentLoaded", () => {
  document.body.insertAdjacentHTML("afterbegin",
    `<div style="background:#fde68a;padding:6px 12px;font:13px sans-serif">DEMO APPLICATION — contains intentional bugs for testing AgentQA Cloud</div>
     <nav aria-label="Main" style="padding:10px 12px;font:15px sans-serif;display:flex;gap:14px;border-bottom:1px solid #ddd">
       <a href="/index.html">Home</a><a href="/products.html">Products</a><a href="/search.html">Search</a>
       <a href="/deals.html">Deals</a><a href="/cart.html">Cart</a><a href="/login.html">Login</a>
       <a href="/register.html">Register</a><a href="/contact.html">Contact</a></nav>`);
});
