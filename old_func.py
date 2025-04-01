# async def price_updates(symbol, interval_seconds):
#     method = "GET"
#     endpoint = '/openApi/spot/v1/ticker/price'
#     params = {
#         "symbol": symbol
#     }
#
#     async with ClientSession(headers=headers) as session:
#         while True:
#             response = await send_request(method, session, endpoint, params)
#             if response:
#                 price = float(response["data"][0]["trades"][0]["price"])
#                 print(f"{symbol}: {price}")
#             await sleep(interval_seconds)



# async def get_symbol_info(symbol):
#     method = "GET"
#     endpoint = '/openApi/spot/v1/common/symbols'
#     params = {
#         "symbol": symbol
#     }
#
#     async with ClientSession(headers=headers) as session:
#         response = await send_request(method, session, endpoint, params)
#         if response:
#             print(f"{symbol}: {response}")