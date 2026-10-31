module top(input clk, input reset, output fetch_cmd_valid, output [31:0] fetch_cmd_addr,
                   output lsu_cmd_valid, output [31:0] lsu_cmd_addr);
  reg [31:0] fetch_word, lsu_data;
  reg fetch_rsp_valid, lsu_rsp_valid;
  always @(posedge clk) begin
    fetch_word <= fetch_word + 32'd1;      // free-running "instruction memory": keeps the pipeline live
    lsu_data <= lsu_data + 32'd1;
    fetch_rsp_valid <= fetch_cmd_valid;    // always eventually acks, never deadlocks waiting
    lsu_rsp_valid <= lsu_cmd_valid;
  end
  VexiiRiscv u_core(
    .PrivilegedPlugin_logic_rdtime(64'd0),
    .PrivilegedPlugin_logic_harts_0_int_m_timer(1'b0),
    .PrivilegedPlugin_logic_harts_0_int_m_software(1'b0),
    .PrivilegedPlugin_logic_harts_0_int_m_external(1'b0),
    .FetchCachelessPlugin_logic_bus_cmd_valid(fetch_cmd_valid),
    .FetchCachelessPlugin_logic_bus_cmd_ready(1'b1),
    .FetchCachelessPlugin_logic_bus_cmd_payload_id(),
    .FetchCachelessPlugin_logic_bus_cmd_payload_address(fetch_cmd_addr),
    .FetchCachelessPlugin_logic_bus_rsp_valid(fetch_rsp_valid),
    .FetchCachelessPlugin_logic_bus_rsp_payload_id(1'd0),
    .FetchCachelessPlugin_logic_bus_rsp_payload_error(1'b0),
    .FetchCachelessPlugin_logic_bus_rsp_payload_word(fetch_word),
    .LsuCachelessPlugin_logic_bus_cmd_valid(lsu_cmd_valid),
    .LsuCachelessPlugin_logic_bus_cmd_ready(1'b1),
    .LsuCachelessPlugin_logic_bus_cmd_payload_id(),
    .LsuCachelessPlugin_logic_bus_cmd_payload_write(),
    .LsuCachelessPlugin_logic_bus_cmd_payload_address(lsu_cmd_addr),
    .LsuCachelessPlugin_logic_bus_cmd_payload_data(),
    .LsuCachelessPlugin_logic_bus_cmd_payload_size(),
    .LsuCachelessPlugin_logic_bus_cmd_payload_mask(),
    .LsuCachelessPlugin_logic_bus_cmd_payload_io(),
    .LsuCachelessPlugin_logic_bus_cmd_payload_fromHart(),
    .LsuCachelessPlugin_logic_bus_cmd_payload_uopId(),
    .LsuCachelessPlugin_logic_bus_rsp_valid(lsu_rsp_valid),
    .LsuCachelessPlugin_logic_bus_rsp_payload_id(1'd0),
    .LsuCachelessPlugin_logic_bus_rsp_payload_error(1'b0),
    .LsuCachelessPlugin_logic_bus_rsp_payload_data(lsu_data),
    .clk(clk), .reset(reset));
endmodule
