module c_ram_sv_1 (input logic clk, we, input logic [5:0] waddr, raddr, input logic [0:0] din, output logic [0:0] dout);
  logic [0:0] mem [0:63];
  always_ff @(posedge clk) begin
    if (we) mem[waddr] <= din;
    dout <= mem[raddr];
  end
endmodule
