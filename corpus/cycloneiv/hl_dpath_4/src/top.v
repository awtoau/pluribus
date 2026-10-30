module top (
  input clk,
  output y
);
reg [7:0] cnt1;
reg [31:0] stim0;
reg [7:0] crc2;
function [7:0] crcf3(input [7:0] cc, input [7:0] x);
  integer i; reg [7:0] rr;
  begin
    rr = cc;
    for (i = 0; i < 8; i = i + 1) rr = (rr[7] ^ x[7 - i]) ? ((rr << 1) ^ 8'h7) : (rr << 1);
    crcf3 = rr;
  end
endfunction
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) begin
  cnt1 <= cnt1 + 8'd1;
end
always @(posedge clk) if (stim0[7] & stim0[6] & stim0[13]) crc2 <= {8{1'b1}}; else if (stim0[25]) crc2 <= crcf3(crc2, {stim0[12], stim0[28], stim0[27], stim0[29], stim0[24], stim0[0], stim0[8], stim0[23]});
always @(posedge clk) y_q <= (^cnt1) ^ (^crc2);
assign y = y_q;
endmodule
