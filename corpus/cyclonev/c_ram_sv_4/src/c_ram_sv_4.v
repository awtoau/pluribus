module c_ram_sv_4 (input logic clk, we, input logic [5:0] waddr, raddr, input logic [3:0] din, output logic [3:0] dout);
  logic [3:0] mem [0:63];
  always_ff @(posedge clk) begin
    if (we) mem[waddr] <= din;
    dout <= mem[raddr];
  end
endmodule
