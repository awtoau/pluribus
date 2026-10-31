module top(input clk, input resetn, output trap, output [7:0] mem_addr_lo, output [3:0] mem_wstrb);
  wire mem_valid, mem_instr, mem_la_read, mem_la_write;
  wire [31:0] mem_addr, mem_wdata, mem_la_addr, mem_la_wdata;
  wire [3:0] mem_la_wstrb;
  reg [31:0] mem_rdata;
  reg mem_ready;
  always @(posedge clk) begin
    mem_rdata <= mem_rdata + 32'd1;      // free-running "memory": keeps fetch/decode/execute live
    mem_ready <= mem_valid;              // always eventually acks, core never deadlocks waiting
  end
  wire [31:0] pcpi_rs1, pcpi_rs2;
  wire [31:0] irq = 32'd0;
  picorv32 #(.ENABLE_PCPI(0), .ENABLE_MUL(0), .ENABLE_DIV(0), .ENABLE_IRQ(0)) u_core(
    .clk(clk), .resetn(resetn), .trap(trap),
    .mem_valid(mem_valid), .mem_instr(mem_instr), .mem_ready(mem_ready),
    .mem_addr(mem_addr), .mem_wdata(mem_wdata), .mem_wstrb(mem_wstrb),
    .mem_rdata(mem_rdata),
    .mem_la_read(mem_la_read), .mem_la_write(mem_la_write), .mem_la_addr(mem_la_addr),
    .mem_la_wdata(mem_la_wdata), .mem_la_wstrb(mem_la_wstrb),
    .pcpi_valid(), .pcpi_insn(), .pcpi_rs1(pcpi_rs1), .pcpi_rs2(pcpi_rs2),
    .pcpi_wr(1'b0), .pcpi_rd(32'd0), .pcpi_wait(1'b0), .pcpi_ready(1'b0),
    .irq(irq), .eoi());
  assign mem_addr_lo = mem_addr[7:0];
endmodule
