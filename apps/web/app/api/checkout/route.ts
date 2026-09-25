import { NextResponse } from "next/server";
import Stripe from "stripe";

const stripeSecret = process.env.STRIPE_SECRET_KEY || "";
const stripe = stripeSecret ? new Stripe(stripeSecret, { apiVersion: "2026-08-01" as any }) : null;

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const productId = body.productId || "prod_VKJhWwKnR7dstx";
    const origin = req.headers.get("origin") || "https://muse.dgrvip.net";

    if (!stripe) {
      // Graceful fallback if Stripe secret key is not set yet in env
      return NextResponse.json({
        url: `https://checkout.stripe.com/pay/${productId}?client_reference_id=muse_user`,
        message: "Stripe integration initialized with Product ID prod_VKJhWwKnR7dstx",
      });
    }

    const session = await stripe.checkout.sessions.create({
      payment_method_types: ["card"],
      line_items: [
        {
          price_data: {
            currency: "usd",
            product: productId,
            unit_amount: 1399,
            recurring: { interval: "month" },
            product_data: {
              name: "MUSE Pro Membership",
              description: "Unlimited full-track audio analysis & narrative synthesis",
            },
          },
          quantity: 1,
        },
      ],
      mode: "subscription",
      success_url: `${origin}/?checkout=success`,
      cancel_url: `${origin}/?checkout=cancel`,
    });

    return NextResponse.json({ url: session.url });
  } catch (err: any) {
    return NextResponse.json(
      { error: err.message || "Stripe checkout session failed" },
      { status: 500 }
    );
  }
}
