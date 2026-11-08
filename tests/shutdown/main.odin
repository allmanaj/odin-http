package main

import http "../.."

import "core:fmt"
import "core:net"
import "core:os"
import "core:strconv"
import "core:time"

main :: proc() {
	port_str := os.get_env_alloc("PORT", context.allocator)
	if port_str == "" { port_str = "18099" }
	port, ok := strconv.parse_int(port_str)
	fmt.assertf(ok, "bad PORT %q", port_str)

	router: http.Router
	http.router_init(&router)
	defer http.router_destroy(&router)

	http.route_get(&router, "/", http.handler(proc(_: ^http.Request, res: ^http.Response) {
		http.respond_plain(res, "ok")
	}))

	http.route_get(&router, "/slow", http.handler(proc(_: ^http.Request, res: ^http.Response) {
		time.sleep(30 * time.Second)
		http.respond_plain(res, "slow")
	}))

	s: http.Server
	http.server_shutdown_on_interrupt(&s)
	err := http.listen_and_serve(&s, http.router_handler(&router), net.Endpoint {
		address = net.IP4_Loopback,
		port    = port,
	})
	fmt.assertf(err == nil, "server stopped with error: %v", err)
}
